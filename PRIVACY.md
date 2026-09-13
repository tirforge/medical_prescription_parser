# Privacy

- Prescription images are sent to Google AI (Gemini/Gemma) for OCR. Free-tier API may retain data for product improvement.
- Indian DB + RxNorm + openFDA lookups are local or keyless public APIs, no patient data sent beyond drug names/salts.
- Do not upload real patient data on free tier. Use a paid tier with data-processing terms or self-host.
- No data is stored server-side beyond session `history` (in-memory, cleared on refresh) unless you enable persistence.
