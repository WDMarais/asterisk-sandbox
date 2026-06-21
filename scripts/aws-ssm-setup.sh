#!/bin/bash
# Operator-side AWS bootstrap to reach the EC2 instance over SSM Session Manager,
# so SSH no longer depends on a source-IP allowlist. Run LOCALLY (your
# workstation / WSL) with an AWS identity that can manage IAM + EC2 -- NOT on the
# VPS. Idempotent: safe to re-run.
#
# What it does:
#   1. create IAM role $ROLE_NAME trusting EC2, attach AmazonSSMManagedInstanceCore
#   2. create instance profile $PROFILE_NAME, add the role
#   3. associate the profile with the instance
#   4. poll until the SSM agent reports the instance Online
#
# Permissions the identity RUNNING this needs (one-time bootstrap -- broader than
# day-to-day connect, which is aws/ssm-connect-policy.json):
#   iam:GetRole iam:CreateRole iam:AttachRolePolicy iam:PassRole
#   iam:GetInstanceProfile iam:CreateInstanceProfile iam:AddRoleToInstanceProfile
#   ec2:DescribeInstances ec2:DescribeIamInstanceProfileAssociations
#   ec2:AssociateIamInstanceProfile
#   ssm:DescribeInstanceInformation
#
# Config (env vars; defaults shown):
#   AWS_REGION=af-south-1   ROLE_NAME=ssm-ec2-role   PROFILE_NAME=ssm-ec2-profile
#   INSTANCE_ID=i-...       (or) INSTANCE_NAME=<Name tag>

set -euo pipefail

AWS_REGION="${AWS_REGION:-af-south-1}"
ROLE_NAME="${ROLE_NAME:-ssm-ec2-role}"
PROFILE_NAME="${PROFILE_NAME:-ssm-ec2-profile}"
MANAGED_POLICY="arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TRUST_DOC="$REPO_ROOT/aws/ec2-ssm-trust-policy.json"

command -v aws >/dev/null || { echo "error: aws CLI not found -- install and 'aws configure' first" >&2; exit 1; }
[[ -f "$TRUST_DOC" ]] || { echo "error: missing $TRUST_DOC" >&2; exit 1; }

# --- identify the instance -------------------------------------------------
INSTANCE_ID="${INSTANCE_ID:-}"
if [[ -z "$INSTANCE_ID" && -n "${INSTANCE_NAME:-}" ]]; then
    INSTANCE_ID="$(aws ec2 describe-instances --region "$AWS_REGION" \
        --filters "Name=tag:Name,Values=$INSTANCE_NAME" "Name=instance-state-name,Values=running" \
        --query 'Reservations[].Instances[].InstanceId' --output text)"
fi
if [[ -z "$INSTANCE_ID" || "$INSTANCE_ID" == "None" ]]; then
    echo "error: set INSTANCE_ID=i-... (or INSTANCE_NAME=<Name tag> to look it up)" >&2
    echo "candidates:" >&2
    aws ec2 describe-instances --region "$AWS_REGION" --output table \
        --query 'Reservations[].Instances[].[InstanceId,PublicIpAddress,State.Name]' >&2 || true
    exit 1
fi
echo "==> target instance: $INSTANCE_ID ($AWS_REGION)"

# --- IAM role --------------------------------------------------------------
echo "==> IAM role $ROLE_NAME"
if aws iam get-role --role-name "$ROLE_NAME" &>/dev/null; then
    echo "role exists"
else
    aws iam create-role --role-name "$ROLE_NAME" \
        --assume-role-policy-document "file://$TRUST_DOC" >/dev/null
    echo "created role"
fi
aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn "$MANAGED_POLICY"  # idempotent
echo "attached AmazonSSMManagedInstanceCore"

# --- instance profile ------------------------------------------------------
echo "==> instance profile $PROFILE_NAME"
if aws iam get-instance-profile --instance-profile-name "$PROFILE_NAME" &>/dev/null; then
    echo "profile exists"
else
    aws iam create-instance-profile --instance-profile-name "$PROFILE_NAME" >/dev/null
    echo "created profile"
    sleep 10  # let the new profile propagate before association
fi
if aws iam get-instance-profile --instance-profile-name "$PROFILE_NAME" \
        --query 'InstanceProfile.Roles[].RoleName' --output text | grep -qw "$ROLE_NAME"; then
    echo "role already in profile"
else
    aws iam add-role-to-instance-profile --instance-profile-name "$PROFILE_NAME" --role-name "$ROLE_NAME"
    echo "added role to profile"
fi

# --- associate with the instance ------------------------------------------
echo "==> associate profile with $INSTANCE_ID"
# The backticks are JMESPath string-literal syntax and must reach the CLI
# unexpanded -- single quotes are correct here, so SC2016 is a false positive.
# shellcheck disable=SC2016
existing="$(aws ec2 describe-iam-instance-profile-associations --region "$AWS_REGION" \
    --filters "Name=instance-id,Values=$INSTANCE_ID" \
    --query 'IamInstanceProfileAssociations[?State==`associated`].IamInstanceProfile.Arn' \
    --output text)"
if [[ -z "$existing" ]]; then
    aws ec2 associate-iam-instance-profile --region "$AWS_REGION" \
        --instance-id "$INSTANCE_ID" --iam-instance-profile "Name=$PROFILE_NAME" >/dev/null
    echo "associated"
elif [[ "$existing" == *"/$PROFILE_NAME" ]]; then
    echo "already associated with $PROFILE_NAME"
else
    echo "warning: instance already has a different profile: $existing" >&2
    echo "leaving as-is -- ensure that role grants AmazonSSMManagedInstanceCore" >&2
fi

# --- wait for the agent to check in ---------------------------------------
echo "==> waiting for SSM agent to report Online (agent dials out on 443; up to ~3 min)"
status=""
for _ in $(seq 1 18); do
    status="$(aws ssm describe-instance-information --region "$AWS_REGION" \
        --filters "Key=InstanceIds,Values=$INSTANCE_ID" \
        --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || true)"
    [[ "$status" == "Online" ]] && break
    sleep 10
done
if [[ "$status" != "Online" ]]; then
    echo "still not Online. On the box, restart the agent:" >&2
    echo "  sudo snap start amazon-ssm-agent || sudo systemctl restart snap.amazon-ssm-agent.amazon-ssm-agent" >&2
    exit 1
fi
echo "online ✓"

echo ""
echo "done -- $INSTANCE_ID is reachable via SSM. next:"
echo "  local plugin + ssh config:  INSTANCE_ID=$INSTANCE_ID bash $REPO_ROOT/scripts/aws-ssm-connect-setup.sh --write"
echo "  smoke test:                 aws ssm start-session --target $INSTANCE_ID --region $AWS_REGION"
echo "  least-priv connect policy:  aws/ssm-connect-policy.json (see notes/ssm-access.md)"
echo "  then close inbound 22 in the instance's security group"
