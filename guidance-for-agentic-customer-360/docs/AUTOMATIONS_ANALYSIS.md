# Amazon Quick Suite Automations - Deployment Analysis

## Current Status: ❌ NOT AVAILABLE VIA API

### What Are Quick Suite Automations?

Quick Suite Automations (formerly Q Automations) are AI-powered workflows that:
- Monitor dashboards for anomalies
- Send automated alerts
- Trigger actions based on data changes
- Use natural language to define conditions

**Example**: "Alert me when revenue drops by 10% week-over-week"

### API Availability

**Checked AWS CLI Commands**:
```bash
aws quicksight help | grep automat
# No automation-specific commands found
```

**Available APIs** (as of January 2025):
- ✅ `create-topic` / `describe-topic` - Q Topics (natural language queries)
- ✅ `start-asset-bundle-export-job` - Export dashboards, datasets, etc.
- ✅ `start-asset-bundle-import-job` - Import asset bundles
- ❌ **No automation APIs** - Cannot export/import automations programmatically

### What CAN Be Automated

**Asset Bundle APIs** (June 2023 release) support:
- ✅ Dashboards
- ✅ Analyses
- ✅ Datasets (including refresh schedules)
- ✅ Data sources
- ✅ Themes
- ✅ VPC connections
- ❌ **Automations** (not included)

### Workaround Options

#### Option 1: Manual Recreation (Current Best Practice)
After automated deployment:
1. Deploy dashboards via `make phase4`
2. Manually create automations in Quick Suite console
3. Document automation configurations in README

**Pros**: Works today, simple
**Cons**: Manual step, not version controlled

#### Option 2: CloudWatch + Lambda Alternative
Replace Quick Suite Automations with AWS-native services:

```python
# Lambda function triggered by CloudWatch Events
def check_revenue_drop(event, context):
    # Query Athena
    result = athena.start_query_execution(
        QueryString="SELECT revenue FROM kpi_trends WHERE date = CURRENT_DATE"
    )
    
    # Check threshold
    if revenue_drop > 0.10:
        sns.publish(
            TopicArn='arn:aws:sns:...',
            Message='Revenue dropped by 10%!'
        )
```

**Pros**: Fully automated, version controlled, works across accounts
**Cons**: More complex, requires Lambda + CloudWatch + SNS setup

#### Option 3: Wait for API Support
Monitor AWS announcements for automation API support.

**Timeline**: Unknown - Q Automations are relatively new (2024)

### Recommendation

**For Distribution**: Use **Option 1** (Manual) + **Option 2** (CloudWatch Alternative)

**Phase 4**: Deploy dashboards (automated)
**Phase 5**: Bedrock Agents (automated) - can include alerting logic
**Manual**: Create Q Automations in console (documented in README)

### Documentation Approach

Create `docs/AUTOMATIONS_SETUP.md`:
```markdown
# Setting Up Quick Suite Automations

After deploying dashboards (Phase 4), create automations manually:

## Revenue Drop Alert

1. Navigate to: Dashboard → Automations
2. Click "Create automation"
3. Configure:
   - Trigger: "When revenue drops by more than 10%"
   - Action: "Send email to team@example.com"
   - Frequency: Daily

## Customer Health Alert

1. Create automation
2. Configure:
   - Trigger: "When at-risk customers increase by 20%"
   - Action: "Send Slack notification"
   - Frequency: Hourly
```

### Alternative: Bedrock Agents for Alerting

Since we're deploying Bedrock agents (Phase 5), we can implement alerting there:

```python
# Bedrock agent action
def check_customer_health():
    # Query Athena
    at_risk_count = query_athena("SELECT COUNT(*) FROM customer_health WHERE health_score < 40")
    
    # Alert if threshold exceeded
    if at_risk_count > threshold:
        send_alert("High number of at-risk customers detected")
```

**Pros**: 
- Fully automated
- Version controlled
- More flexible than Q Automations
- Can integrate with any system

## Summary

**Can we automate Quick Suite Automations deployment?**
- ❌ **NO** - Not available via API yet

**Best approach for distribution:**
1. ✅ Automate dashboards (Phase 4) - **DONE**
2. ✅ Automate Bedrock agents with alerting (Phase 5) - **RECOMMENDED**
3. 📝 Document manual Q Automation setup - **FALLBACK**

**Recommendation**: Focus on Bedrock agents for automated alerting instead of Q Automations. More powerful, fully automatable, and version controlled.
