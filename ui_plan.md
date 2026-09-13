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

- [ ] **`.streamlit/config.toml` medical theme**: calm teal/blue primary,
      custom `[theme.light]` + `[theme.dark]` so both modes look designed
      (Streamlit docs: per-theme colors, radius, fonts). Fixes the table
      problem properly instead of hardcoded HTML colors.
- [ ] **Page identity**: `st.set_page_config` title/icon/about menu
      (🏥 + "About this app" with disclaimer + data-use transparency —
      healthcare UX rule: trust through transparency).
- [ ] **Sidebar**: about, model picker, API-key input, enhance toggle,
      disclaimer. (medscan-lens pattern)
- [ ] **Tabs**: `🔍 Scan Medicine | 📄 Prescription | 📜 History` instead of
      one endless scroll. (medscan-lens pattern)
- [ ] **Progress feedback**: `st.status`/`st.progress` with stages
      (upload → enhance → read → verify → safety) instead of one spinner.
- [ ] **Metric cards**: `st.metric` row after parse — medicines found,
      verified, review flags — glanceable summary before details.
- [ ] **Replace raw-HTML tables with `st.dataframe`**: theme-aware, sortable,
      mobile-scrollable; deletes the whole class of contrast bugs.

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
