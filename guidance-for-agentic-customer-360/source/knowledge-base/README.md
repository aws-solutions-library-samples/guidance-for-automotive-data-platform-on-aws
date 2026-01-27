# Knowledge Base Documentation

This directory contains markdown documentation that gets vectorized and indexed by Bedrock Knowledge Base for semantic search.

## Structure

```
knowledge-base/
├── battery-remediation-playbook.md    # Battery and power system issues
├── customer-success-playbook.md       # Customer engagement strategies (TODO)
├── analytics-metadata.md              # Data schema and KPI definitions (TODO)
└── README.md                          # This file
```

## File Format Guidelines

### Why Markdown?

Markdown provides:
- ✅ Rich semantic context for LLMs
- ✅ Natural language structure
- ✅ Better chunking than CSV
- ✅ Easy to maintain and version control
- ✅ Human-readable documentation

### Document Structure

Each playbook should follow this structure:

```markdown
# [Topic] Playbook

Brief introduction explaining the scope and purpose.

---

## Category 1

### Issue Name

**Symptoms:**
- Bullet list of observable symptoms
- Include metrics and thresholds

**Severity:** Critical | High | Medium | Low

**Root Cause:** Brief explanation

**Recommended Action:**
Step-by-step remediation
- **Success Rate:** XX%
- **Average Resolution Time:** X days
- **Revenue Recovery Rate:** XX%

**Escalation Trigger:**
When to escalate to next level

**Customer Communication Template:**
> "Template message for customer outreach"

---
```

## Deployment

### 1. Upload to S3

Documents are automatically synced to the Knowledge Base S3 bucket:

```bash
aws s3 sync source/knowledge-base/ \
  s3://cx360-knowledge-base-${ACCOUNT_ID}/docs/ \
  --exclude "README.md" \
  --exclude "*.csv"
```

### 2. Sync Data Source

Trigger Bedrock to ingest and vectorize:

```bash
aws bedrock-agent start-ingestion-job \
  --knowledge-base-id <KB_ID> \
  --data-source-id <DS_ID>
```

### 3. Verify

Query the knowledge base to test:

```bash
aws bedrock-agent-runtime retrieve \
  --knowledge-base-id <KB_ID> \
  --retrieval-query "How do I handle battery degradation?"
```

## Migration from CSV

### Before (CSV)
```csv
root_cause,symptom_pattern,severity,recommended_action
Supplier Batch Defect,Battery health <80%,Critical,Replace battery
```

**Problems**:
- No context or narrative
- Poor chunking (one row = one vector)
- Hard to understand relationships
- Metadata separate from content

### After (Markdown)
```markdown
## Supplier Batch Defect Issues

### Early Battery Health Degradation

**Symptoms:**
- Battery health drops below 80% within first 12 months
- Typically affects Q2 2024 production batches

**Root Cause:** 
Supplier batch defect in thermal management components

**Recommended Action:**
Proactive battery replacement under warranty...
```

**Benefits**:
- Rich context for semantic search
- Natural language for LLM understanding
- Better chunking (by section)
- Self-documenting

## Best Practices

1. **One topic per file**: Don't mix battery issues with customer success strategies
2. **Use headers**: H2 for categories, H3 for specific issues
3. **Include examples**: Real-world scenarios help LLM understanding
4. **Add metadata**: Success rates, timelines, costs
5. **Update regularly**: Keep playbooks current with new learnings
6. **Version control**: Use git to track changes

## Vector Storage

Documents are chunked and embedded using:
- **Model**: Amazon Titan Embed Text v1 (1,536 dimensions)
- **Chunk size**: ~500 tokens with 20% overlap
- **Storage**: Aurora PostgreSQL with pgvector extension

See [VECTOR_STORAGE_DECISION.md](../../docs/VECTOR_STORAGE_DECISION.md) for details.

## TODO

- [ ] Convert remaining CSV files to markdown
- [ ] Create customer-success-playbook.md
- [ ] Create analytics-metadata.md
- [ ] Add fleet operations procedures
- [ ] Document data schema and KPIs
