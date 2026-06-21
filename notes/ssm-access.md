# VPS access via AWS SSM Session Manager

## Why

SSH to the VPS was gated by a source-IP allowlist (a security-group rule pinned
to a single address). A rotating VPN IP means constantly editing that rule. The
fix is to authenticate by *identity* (IAM) rather than by *source address*.

AWS SSM Session Manager does exactly that, and lets us **close inbound port 22
entirely**: the SSM agent on the box dials *out* to AWS over 443, so there is no
inbound SSH surface to attack or to allowlist. Chosen over a hardened-but-open
SSH port (still a public endpoint, only a key away) and over Tailscale (adds a
third-party SaaS dependency) because it is AWS-native, the agent ships
preinstalled on the Ubuntu AMI, and it removes the open port rather than
defending it.

## How it works

```
workstation  --(aws ssm start-session, IAM-authed over 443)-->  AWS SSM
   (you)                                                            |
                                                                    | 443 (outbound from box)
                                                          EC2 instance + ssm-agent
                                                          (no inbound 22 needed)
```

`ssh`, `scp`, `rsync`, and git-over-ssh tunnel through SSM via an SSH
`ProxyCommand`; SSM is only the transport, so SSH still does user auth with your
existing key. Day-to-day this is "one login": with the AWS CLI configured, every
connection just uses those credentials — no per-connection IP step. (On SSO/MFA
you re-auth only when the temporary credentials expire.)

## Two permission scopes

Deliberately separated so day-to-day access is least-privilege:

| Scope | Who/when | What it can do | Where defined |
|---|---|---|---|
| **Bootstrap** | your admin-ish identity, one-time | create the IAM role + instance profile, attach to the instance | listed in `scripts/aws-ssm-setup.sh` header |
| **Instance role** | the EC2 box, ongoing | let the agent talk to SSM | AWS-managed `AmazonSSMManagedInstanceCore` (trust: `aws/ec2-ssm-trust-policy.json`) |
| **Connect** | your day-to-day identity, ongoing | start/stop a session on *this one instance* only | `aws/ssm-connect-policy.json` |

`aws/ssm-connect-policy.json` is the minimal grant for normal use: describe (to
discover the instance), `StartSession` scoped to this instance's ARN + the two
session documents, and terminate/resume scoped to your own sessions. Fill the
placeholders before attaching it:

- `REGION` → `af-south-1`
- `ACCOUNT_ID` → your 12-digit account id (`aws sts get-caller-identity --query Account --output text`)
- `INSTANCE_ID` → the `i-...` from setup
- `${aws:username}` works for IAM users; for SSO/role sessions the session ARN
  uses the role-session name instead — broaden that statement if terminate is denied.

## Repo artifacts

```
aws/ec2-ssm-trust-policy.json   EC2 trust policy for the instance role
aws/ssm-connect-policy.json     least-priv policy for your connecting identity
scripts/aws-ssm-setup.sh        [run locally] create role/profile, attach, wait Online
scripts/aws-ssm-connect-setup.sh[run locally] install plugin + ssh config block
```

These run on your **workstation** with AWS credentials — unlike the on-VPS
lifecycle scripts (`provision.sh` etc.), which run as `ubuntu` on the box.

## Runbook

Prerequisite (can't be scripted — it's the credential bootstrap):

```sh
aws configure          # access key + secret, region af-south-1
# or: aws configure sso
aws sts get-caller-identity   # confirm you're authenticated
```

Then:

```sh
# 1. find the instance (note the i-... id)
aws ec2 describe-instances --region af-south-1 --output table \
  --query 'Reservations[].Instances[].[InstanceId,PublicIpAddress,State.Name]'

# 2. create role + profile, attach to instance, wait for Online
INSTANCE_ID=i-xxxx bash scripts/aws-ssm-setup.sh
#    (or, to look up by Name tag: INSTANCE_NAME=pbx bash scripts/aws-ssm-setup.sh)

# 3. local plugin + ssh config
INSTANCE_ID=i-xxxx bash scripts/aws-ssm-connect-setup.sh --write

# 4. smoke test
aws ssm start-session --target i-xxxx --region af-south-1   # shell as ssm-user
ssh pbx                                                     # shell as ubuntu (over SSM)

# 5. lock down: attach aws/ssm-connect-policy.json to your day-to-day identity,
#    then delete the inbound port-22 rule from the instance's security group.
```

## Break-glass / recovery

The point of SSM is that it *is* the out-of-band path once 22 is closed. If the
SSM agent itself stops checking in:

- EC2 console → instance → Connect → **EC2 Instance Connect** (browser SSH;
  temporarily re-add an inbound-22 rule for the console's address if needed), or
- stop the instance, detach the root volume, fix on another box, reattach.

On the box, the agent is a snap service:

```sh
snap services amazon-ssm-agent
sudo snap restart amazon-ssm-agent
```

## Rollback

To revert to IP-allowlisted SSH: re-add an inbound TCP/22 rule for your address
in the security group. The SSM role/profile can stay attached harmlessly.
