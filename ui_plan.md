# UI Improvement Plan

Researched 2026-09-13 from: Streamlit theming docs, `awesome-streamlit-themes`,
Microsoft `Streamlit_UI_Template`, healthcare UX guides (Eleken, Onething,
Kitrum, HTD, Aufait). Nothing below is implemented yet.

## Our current UI problems (from real usage)

1. No theme — stock Streamlit; tables already broke once in dark mode
   (patched with hardcoded colors instead of a real fix).
2. One giant scrolling page: upload → images → tables → verify → safety →
   flags → copy. No structure, no progress feedback.
3. No sidebar at all (model picker was even promised in a comment, never built).
4. Tables overflow on phones; app is desktop-shaped.
5. Dev-flavored output (`st.code` blocks, raw JSON) shown to patients.
6. No accessibility pass (contrast, font size, keyboard, screen reader).

## Phase 1 — Quick wins, Streamlit-native (no CSS hacks)

- [x] **`.streamlit/config.toml` medical theme** (teal, custom light+dark).
      DONE 2026-09-13.
- [x] **Page identity** (title/icon/about menu). DONE 2026-09-13.
- [x] **Sidebar** (model picker, key input, about, disclaimer). DONE 2026-09-13.
- [x] **Tabs**: `🔍 Scan Medicine | 📄 Prescription | 📜 History`. DONE 2026-09-13.
- [x] **Progress feedback** (`st.status` stages) + **metric cards**. DONE 2026-09-13.
- [x] **Raw-HTML tables → `st.dataframe`** (theme-aware). DONE 2026-09-13.
- [x] **Sample-image button** (select from `accuracy_test/`). DONE 2026-09-13.
- [x] **Export** (CSV + TXT report + Print-as-PDF tip). DONE 2026-09-13.
- [x] **History tab** (session, 20 entries, view/clear). DONE 2026-09-13.

## Phase 2 — Healthcare UX (what top medical apps do)

- [ ] **Plain-language pass**: reading level of patients ≠ devs. Keep the
      simplified side-effect lines; rewrite headers/labels the same way
      ("Medicine Verification" → "Is this medicine genuine?").
- [ ] **Progressive disclosure**: summary first (metrics + flags), details
      collapsed — partially done, apply everywhere.
- [ ] **Role toggle**: Patient view (simple words, big text) vs Doctor view
      (full tables, JSON, compositions). Healthcare rule: personalize by role.
- [ ] **Prevent mistakes**: confirm before clearing results, undo-friendly
      flows, warnings when image quality is poor (blur detection before
      sending to Gemini).
- [ ] **Language**: your prescriptions carry Bengali instructions — evaluate
      Bengali/English toggle for labels and simplified effects.
- [ ] **Print/export view**: clean print stylesheet + PDF/CSV download so
      doctors can file it (also in todo.md).

## Phase 3 — Polish

- [ ] **Multipage navigation** (`st.navigation`): Home / Scan / History /
      About as real pages when the app outgrows tabs.
- [ ] **Custom CSS pass** using Microsoft `Streamlit_UI_Template` patterns
      (rounded cards, styled buttons) — only after the theme file exists,
      never bare `.stApp` hacks that flash/fight the theme.
- [ ] **Loading skeletons + empty states**: friendly first-run screen with
      "Try a sample" instead of an empty uploader.
- [ ] **Mobile check**: 360px-wide pass — tables scroll, buttons thumb-sized,
      upload works from phone camera.
- [ ] **Accessibility checklist**: contrast ≥ 4.5:1, ≥16px body, keyboard
      operability, meaningful expander labels for screen readers
      (EAA makes this a legal must in EU).

## Sources

- Theming: `docs.streamlit.io/develop/concepts/configuration/theming`
  (light+dark custom themes, per-sidebar colors)
- Theme gallery: `jmedia65/awesome-streamlit-themes`
- CSS patterns: `microsoft/Streamlit_UI_Template`, `dataprofessor/streamlit-custom-theme`
- Healthcare UX 2026: Eleken (role-based, minimize clicks), Onething
  (plain language, selection-over-typing), Kitrum (error prevention,
  accessibility-first), HTD (progress visualization, personalization)
