"""ADP Foundation — data quality / observability dashboard.

This directory ships:

* :mod:`metrics` — single-source-of-truth namespace, metric and
  dimension names, and the catalog of valid dimension values.
* :mod:`dashboard` — CloudWatch dashboard body builder, optional CDK
  construct (``QualityDashboard``), and CLI for emitting the body
  JSON.

Both files are loaded as **top-level** modules — the directory uses
kebab-case (matching siblings ``data-products/`` and
``athena-queries/``), so it is not a true Python package. Tests and
the CLI add the directory to ``sys.path`` and ``import dashboard`` /
``import metrics`` directly.

See ``README.md`` in this directory for the deploy + verify runbook.
"""
