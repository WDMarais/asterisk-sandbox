#!/bin/bash
# Lock down: close inbound SSH (tcp/22) on the instance's security group(s) once
# SSM access works. SSM is unaffected (the agent dials OUT on 443); PBX ports
# (80/443/8089/5060) are left untouched. Run locally. Reads config from
# scripts/.env (AWS_PROFILE / AWS_REGION / INSTANCE_ID).
#
# The backticks in the --query expressions are JMESPath literals and must reach
# the CLI unexpanded -- single quotes are correct, so SC2016 is a false positive.
# shellcheck disable=SC2016

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ -f "$SCRIPT_DIR/.env" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$SCRIPT_DIR/.env"
    set +a
fi
REGION="${AWS_REGION:-af-south-1}"
: "${INSTANCE_ID:?INSTANCE_ID not set (check scripts/.env)}"

command -v aws >/dev/null || { echo "error: aws CLI not found" >&2; exit 1; }

SGS=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --region "$REGION" --query 'Reservations[].Instances[].SecurityGroups[].GroupId' --output text)
echo "instance $INSTANCE_ID security groups: $SGS"

for sg in $SGS; do
  echo "=== $sg : all inbound rules (for your review) ==="
  aws ec2 describe-security-group-rules --region "$REGION" --filters Name=group-id,Values="$sg" --query 'SecurityGroupRules[?IsEgress==`false`].[SecurityGroupRuleId,IpProtocol,FromPort,ToPort,CidrIpv4,CidrIpv6]' --output table

  echo "--- revoking tcp/22 rules in $sg ---"
  ids=$(aws ec2 describe-security-group-rules --region "$REGION" --filters Name=group-id,Values="$sg" --query 'SecurityGroupRules[?IsEgress==`false` && IpProtocol==`tcp` && FromPort<=`22` && ToPort>=`22`].SecurityGroupRuleId' --output text)
  if [ -z "$ids" ]; then echo "no tcp/22 rules found"; continue; fi
  for rid in $ids; do
    aws ec2 revoke-security-group-ingress --region "$REGION" --group-id "$sg" --security-group-rule-ids "$rid" >/dev/null
    echo "revoked $rid"
  done
done

echo "done -- inbound 22 closed; 'ssh pbx' (over SSM) still works."
