

# UI Improvement Plan

Researched 2026-09-13 from: Streamlit theming docs, `awesome-streamlit-themes`,
Microsoft `Streamlit_UI_Template`, healthcare UX guides (Eleken, Onething,
Kitrum, HTD, Aufait). Status reviewed 2026-09-13: Phase 1 shipped, most of
Phase 2 and Phase 3 is now wired into `prescription.py` + `styles.css`
(see checkboxes). Remaining TODOs are marked inline.

## Our current UI problems (from real usage — all resolved 2026-09-13)

1. ~~No theme~~ — unified teal theme in `.streamlit/config.toml` +
   `styles.css` with full dark-mode variants (was blue vs teal vs navy).
2. ~~One giant scrolling page~~ — tabbed flow
   (`📄 Prescription | 🔍 Scan Medicine | 📜 History`, prescription first),
   staged `st.progress` + `st.status`, skeleton shimmer, medicine cards.
3. ~~No sidebar~~ — sidebar has model picker, key input, role + language +
   big-text toggles, disclaimer.
4. ~~Tables overflow on phones~~ — `st.dataframe` scrolls, 44–48px targets,
   920px/720px breakpoints.
5. ~~Dev output shown to patients~~ — JSON/full tables gated behind
   Doctor view; Patient view gets plain words.
6. ~~No accessibility pass~~ — focus-visible rings, keyboard tabs,
   contrast-checked pairs, A+ big-text mode.

## Phase 1 — Quick wins, Streamlit-native (no CSS hacks)

- [x] **`.streamlit/config.toml` medical theme** (teal, custom light+dark).
      DONE 2026-09-13.
- [x] **Page identity** (title/icon/about menu). DONE 2026-09-13.
- [x] **Sidebar** (model picker, key input, about, disclaimer). DONE 2026-09-13.
- [x] **Tabs**: `📄 Prescription | 🔍 Scan Medicine | 📜 History`
      (prescription-first order — locked user decision). DONE 2026-09-13.
- [x] **Progress feedback** (`st.status` stages) + **metric cards**. DONE 2026-09-13.
- [x] **Raw-HTML tables → `st.dataframe`** (theme-aware). DONE 2026-09-13.
- [x] **Sample-image button** (select from `accuracy_test/`). DONE 2026-09-13.
- [x] **Export** (CSV + TXT report + Print-as-PDF tip). DONE 2026-09-13.
- [x] **History tab** (session, 20 entries, view/clear). DONE 2026-09-13.

## Phase 2 — Healthcare UX (all wired 2026-09-13 unless noted)

- [~] **Plain-language pass**: side-effect lines simplified; headers/labels
      rewritten in the preview. TODO: finish the same rewrite pass inside
      `prescription.py` labels (partially done via EN/BN label dict).
- [x] **Progressive disclosure**: metrics + risk banner + flags first,
      full cards/JSON/DailyMed in expanders + Doctor view.
- [x] **Role toggle**: Patient (simple, big text) vs Doctor (tables, JSON,
      compositions) in sidebar + preview toolbar.
- [x] **Prevent mistakes**: confirm-before-clear history, blur warning
      before vision calls, QR final-proof guidance.
- [x] **Language**: Bengali/English toggle for labels (sidebar + preview).
- [x] **Print/export view**: print stylesheet + CSV/TXT/PDF download.

## Phase 3 — Polish

- [ ] TODO **Multipage navigation** (`st.navigation`): Home / Scan / History /
      About as real pages when the app outgrows tabs. (Kept tabs for now —
      still the open structural question.)
- [x] **Custom CSS pass** (rounded cards, pill buttons, staged progress,
      skeletons) — theme-aware, no bare `.stApp` hacks. DONE 2026-09-13.
- [x] **Loading skeletons + empty states** + Try-a-sample. DONE 2026-09-13.
- [x] **Mobile check**: tables scroll, 44–48px targets, breakpoints.
      DONE 2026-09-13.
- [x] **Accessibility checklist**: contrast pairs, 16px+ body + A+ mode,
      keyboard tabs, focus rings, labelled expanders. DONE 2026-09-13.

## Preview companion (`rx-prescription-app.html`)

Marketing + interaction preview mirroring the app: hero, upload-gated demo
(Prescription first), feature triplet, real-number stats (254,000 / 4 / 20),
result-reading split, single CTA. Toolbar mirrors app decisions: role,
EN/বাং, A+ text, working copy/CSV/TXT.

TODO (unresolved, kept explicit):
- Live backend fetch in the preview: WIRED to `http://127.0.0.1:8000`
  (`/health` status pill + POST `/parse` with demo fallback; `api.py` has
  CORS, `/health`, offline `/verify`). Still open: deployed base URL + key
  story for hosted use.
- Real prescription imagery (PHI — placeholder stands until consented samples exist).
- Tabs vs multipage navigation (see Phase 3).

## Sources

- Theming: `docs.streamlit.io/develop/concepts/configuration/theming`
  (light+dark custom themes, per-sidebar colors)
- Theme gallery: `jmedia65/awesome-streamlit-themes`
- CSS patterns: `microsoft/Streamlit_UI_Template`, `dataprofessor/streamlit-custom-theme`
- Healthcare UX 2026: Eleken (role-based, minimize clicks), Onething
  (plain language, selection-over-typing), Kitrum (error prevention,
  accessibility-first), HTD (progress visualization, personalization)
