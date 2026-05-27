# Customer Churn Risk Analysis Playbook

This playbook provides guidance on identifying, analyzing, and mitigating customer churn risk based on health scores, behavioral patterns, and root cause analysis.

---

## Understanding Customer Health Segments

### Health Score Ranges

- **Thriving** (80-100): Highly engaged, low risk
- **Healthy** (60-79): Stable, moderate engagement
- **At Risk** (40-59): Declining engagement, intervention needed
- **Needs Attention** (20-39): High churn risk, immediate action required
- **Critical** (<20): Imminent churn, executive escalation

### Risk Indicators

**Primary Metrics:**
- Health score trend (declining over 30+ days)
- Open support cases (unresolved issues)
- Service appointment frequency (>4 in 90 days)
- Satisfaction score (<3.0)
- Revenue at risk (based on lifetime value)

**Behavioral Signals:**
- Low engagement (no app usage, no service visits)
- High case volume (>5 cases in 90 days)
- Recurring product issues (same problem multiple times)

---

## Root Cause Categories

### 1. Excessive Service Visits

**Definition:** Customer has required 4+ service appointments within 90 days

**Common Patterns:**

#### Pattern A: Open Cases Contributing Factor
**Symptoms:**
- Multiple service visits for same issue
- One or more cases remain unresolved
- Customer frustration increasing with each visit

**Severity Levels:**
- **Critical**: 6+ visits, multiple open cases, health score <30
- **High**: 4-5 visits, 1-2 open cases, health score 30-50
- **Medium**: 4 visits, issues being resolved, health score >50

**Intervention Strategy:**
1. Assign dedicated case manager
2. Root cause analysis by engineering team
3. Expedited parts/service scheduling
4. Proactive communication every 48 hours
5. Consider goodwill gesture (service credit, loaner vehicle)

**Success Metrics:**
- Case resolution within 7 days
- Health score improvement >15 points
- No repeat visits for same issue within 90 days

#### Pattern B: Low Engagement Contributing Factor
**Symptoms:**
- Frequent service visits but low app usage
- Minimal interaction with customer success team
- Service-only relationship (no community engagement)

**Intervention Strategy:**
1. Personalized onboarding to digital tools
2. Highlight preventive maintenance benefits
3. Invite to customer events/community
4. Offer premium support tier trial

---

### 2. Poor Customer Experience

**Definition:** Low satisfaction scores (<3.5) combined with declining health score

**Common Patterns:**

#### Pattern A: Low Engagement
**Symptoms:**
- Satisfaction scores 2.0-3.5
- Minimal app usage or service interaction
- No response to outreach attempts
- Health score declining steadily

**Severity Levels:**
- **Critical**: Satisfaction <2.5, health score <25, 60+ days at risk
- **High**: Satisfaction 2.5-3.5, health score 25-40, 30-60 days at risk
- **Medium**: Satisfaction 3.5-4.0, health score 40-60, <30 days at risk

**Intervention Strategy:**
1. Executive outreach (VP/Director level)
2. Comprehensive account review
3. Personalized success plan
4. Quarterly business reviews
5. Early access to new features/services

**Customer Communication Template:**
> "We've noticed you haven't been as engaged with [Product/Service] recently, and we want to ensure you're getting maximum value from your investment. I'd like to schedule a brief call to understand your experience and explore how we can better support your needs."

**Revenue Recovery Rate:** 65-75% (if caught early)

---

### 3. Recurring Product Issues

**Definition:** Same component or system has failed 2+ times within 6 months

**Common Patterns:**

#### Pattern A: High Case Volume
**Symptoms:**
- 5+ support cases in 90 days
- Multiple cases for same product issue
- Customer losing confidence in product reliability
- Health score declining with each incident

**Severity Levels:**
- **Critical**: 3+ failures of same component, health score <30
- **High**: 2 failures, multiple related issues, health score 30-50
- **Medium**: 2 failures, isolated issue, health score >50

**Intervention Strategy:**
1. Immediate engineering escalation
2. Component replacement with upgraded part
3. Extended warranty on affected system
4. Proactive monitoring for similar issues
5. Consider vehicle swap if pattern continues

**Customer Communication Template:**
> "We're aware of the recurring issue with your [component] and want to assure you this is not acceptable. Our engineering team has identified the root cause, and we're implementing a permanent solution. We're replacing the component with an upgraded version and extending your warranty on this system by 2 years."

**Success Metrics:**
- Zero recurrence within 6 months
- Health score recovery to >60
- Customer satisfaction >4.5 on resolution

---

### 4. Unresolved Support Cases

**Definition:** One or more support cases open for >14 days without resolution

**Common Patterns:**

#### Pattern A: Open Cases
**Symptoms:**
- Cases aging beyond SLA
- Multiple follow-ups from customer
- Escalations to management
- Health score dropping 5+ points per week

**Severity Levels:**
- **Critical**: Cases open >30 days, health score <25, executive escalation
- **High**: Cases open 14-30 days, health score 25-45, manager escalation
- **Medium**: Cases open 7-14 days, health score >45, standard escalation

**Intervention Strategy:**
1. Immediate case review by senior support
2. Assign dedicated resolver (single point of contact)
3. Daily status updates to customer
4. Escalate to product/engineering if needed
5. Set hard deadline for resolution (3-5 days)

**Escalation Triggers:**
- No progress after 48 hours
- Customer requests escalation
- Health score drops below 30
- Revenue at risk >$5,000

**Customer Communication Template:**
> "I'm personally taking ownership of your case to ensure rapid resolution. I've reviewed the history and identified the path forward. Here's what we're doing: [specific actions]. I'll update you daily at [time], and my direct line is [number]. We're committed to resolving this by [date]."

**Success Metrics:**
- Case resolution within 5 days
- Customer satisfaction >4.0 on resolution
- Health score stabilization within 14 days

---

### 5. Frequent Support Needs

**Definition:** High case volume (>5 cases in 90 days) even if resolved quickly

**Common Patterns:**

#### Pattern A: High Case Volume
**Symptoms:**
- Many cases but all resolved within SLA
- Customer becoming dependent on support
- Indicates product complexity or training gap
- Health score stable but not improving

**Severity Levels:**
- **Critical**: >10 cases in 90 days, health score declining
- **High**: 7-10 cases in 90 days, health score flat
- **Medium**: 5-7 cases in 90 days, health score improving

**Intervention Strategy:**
1. Comprehensive training session (1-on-1)
2. Create personalized quick reference guide
3. Assign customer success manager
4. Proactive check-ins (weekly for 30 days)
5. Identify product UX improvements

**Root Cause Analysis:**
- Is product too complex?
- Is documentation inadequate?
- Is customer in wrong product tier?
- Are there missing features?

**Success Metrics:**
- Case volume reduction by 50% within 60 days
- Health score improvement >10 points
- Customer self-service rate increase

---

### 6. Poor Service Experience

**Definition:** Negative service interactions (long wait times, poor communication, incomplete repairs)

**Common Patterns:**

#### Pattern A: Low Engagement + High Severity
**Symptoms:**
- Service satisfaction scores <3.0
- Long wait times for appointments (>7 days)
- Multiple visits for same repair
- Customer avoiding service center

**Intervention Strategy:**
1. Priority scheduling for future appointments
2. Loaner vehicle for repairs >4 hours
3. Service center manager follow-up
4. Complimentary service package
5. Alternative service center options

**Customer Communication Template:**
> "We fell short of our service standards during your recent visit, and I apologize. To make this right, we're providing [specific remedy]. For your next service, you'll have priority scheduling and a dedicated service advisor. Your satisfaction is our priority."

---

## Intervention Prioritization Matrix

### Critical Priority (Immediate Action - Within 24 Hours)
- Health score <25 AND revenue at risk >$5,000
- Open cases >30 days with executive escalation
- Recurring product issues (3+ failures)
- Satisfaction score <2.0 with declining trend

**Actions:**
- Executive outreach
- Dedicated case manager
- Daily status updates
- Goodwill gestures authorized

### High Priority (Action Within 48 Hours)
- Health score 25-40 AND revenue at risk $2,000-$5,000
- Open cases 14-30 days
- Excessive service visits (5+)
- Satisfaction score 2.0-3.0

**Actions:**
- Manager-level outreach
- Expedited resolution
- Weekly check-ins
- Service credits considered

### Medium Priority (Action Within 5 Days)
- Health score 40-60 AND revenue at risk <$2,000
- Open cases 7-14 days
- Frequent support needs (5-7 cases)
- Satisfaction score 3.0-3.5

**Actions:**
- CSM outreach
- Standard escalation
- Bi-weekly check-ins
- Training/education focus

---

## Success Metrics

### Customer Recovery Rates by Root Cause

| Root Cause | Recovery Rate | Avg Time to Recovery | Revenue Recovery |
|------------|---------------|---------------------|------------------|
| Excessive Service Visits | 78% | 21 days | 71% |
| Poor Customer Experience | 68% | 35 days | 65% |
| Recurring Product Issues | 85% | 14 days | 83% |
| Unresolved Support Cases | 82% | 10 days | 79% |
| Frequent Support Needs | 91% | 28 days | 88% |
| Poor Service Experience | 73% | 18 days | 70% |

### Health Score Recovery Targets

- **Critical → Needs Attention**: 15+ point improvement in 14 days
- **Needs Attention → At Risk**: 20+ point improvement in 30 days
- **At Risk → Healthy**: 15+ point improvement in 45 days

---

## Proactive Monitoring

### Daily Checks
- New customers entering "Critical" segment
- Open cases aging beyond 7 days
- Health score drops >10 points in 7 days

### Weekly Reviews
- Customers at risk for 30+ days
- Recurring product issue patterns
- Service satisfaction trends

### Monthly Analysis
- Churn rate by root cause
- Intervention effectiveness
- Revenue recovery rates
- Predictive model accuracy

---

## Usage Guidelines

**For Customer Success Managers:**
1. Review daily dashboard for priority customers
2. Match customer patterns to playbook categories
3. Execute intervention strategy within SLA
4. Document outcomes for continuous improvement

**For Support Teams:**
1. Flag cases approaching SLA breach
2. Identify recurring issue patterns
3. Escalate per severity guidelines
4. Provide detailed case notes for CSM handoff

**For Product/Engineering:**
1. Review recurring product issues weekly
2. Prioritize fixes based on churn impact
3. Provide timeline estimates for resolutions
4. Participate in critical customer escalations
