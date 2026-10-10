E-WASTE CHAINGUARD — TRAINING + TESTING DATA (CSV, PDF, PNG)

Each split contains:
- datasets/: all 13 CSV datasets, partitioned by claim where applicable
- evidence/pdf/: synthetic PDF evidence samples
- evidence/images/: synthetic PNG evidence illustrations

The CSV claim split uses 120 training claims and 30 testing claims. Evidence documents with a known linked claim are placed in the matching split. Generic or unmapped evidence samples are placed in training by default. See evidence_split_manifest.csv for file-level mapping.

IMPORTANT: All content is synthetic. PDFs and images are demo-only examples, not real certificates, receipts, photos, legal documents, or regulatory evidence. Some are intentionally suspicious for workflow testing. PNG files are illustrations, not real recycling-site photographs.

For machine-learning evaluation, use only labels and features available at prediction time. These synthetic files do not validate real-world fraud-detection accuracy.
