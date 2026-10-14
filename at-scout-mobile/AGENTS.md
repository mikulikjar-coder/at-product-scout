This is an Expo/React Native mobile application. Prioritize mobile-first patterns, performance, and cross-platform compatibility.

## Expo has changed — do not trust your training data

Expo ships breaking changes every SDK release. APIs you remember are likely renamed, moved, or removed. Before writing any code that touches an Expo, EAS, or React Native API:

1. Read the major version of the `expo` package in `package.json`.
2. Fetch the matching versioned docs: `https://docs.expo.dev/versions/v<major>.0.0/`
3. For anything else, fetch https://docs.expo.dev/llms.txt — an index of all Expo docs with corrections to common LLM misconceptions. Follow its links to the specific page you need; never answer from memory.

## Commands

Use `bunx` instead of `npx` if the project uses bun (`bun.lock` present).

```bash
npx expo install <package>  # ALWAYS use instead of npm/yarn/pnpm/bun add — resolves SDK-compatible versions
npx expo start              # start the dev server
npx expo lint               # lint
npx tsc --noEmit            # typecheck
npx expo-doctor             # diagnose dependency and config issues
npx expo install --fix      # fix incompatible package versions
```

Run lint and typecheck before declaring any task done.

## Navigation & Routing

- Use **Expo Router** for all navigation. Routes live in `src/app/` — every file there is a screen, `_layout.tsx` files define navigators. Keep non-route code (components, hooks, utils) outside `src/app/`.
- Import `Link`, `router`, and `useLocalSearchParams` from `expo-router`.
- Docs: https://docs.expo.dev/router/introduction.md

## Building with EAS

Use EAS to build, sign, and submit the app in the cloud (`eas build`, `eas submit`) and to ship over-the-air updates (`eas update`) — no local Xcode or Android Studio required. Run EAS CLI as `bunx eas-cli <command>` in Bun projects, or `npx eas-cli@latest <command>` otherwise; substitute that for bare `eas` in docs examples.
Docs: https://docs.expo.dev/eas/index.md

## Rules

- If `ios/` and `android/` directories do not exist, they are generated (Continuous Native Generation). Never create or edit them by hand — configure native behavior in `app.json` and config plugins.
- Expo Go only includes its bundled native modules. After adding a library with native code, the app needs a development build: `npx expo run:ios|android` locally, or `eas build --profile development`.
- Prefer recommended Expo modules over third-party libraries, and check your available skills before adding dependencies. Docs: https://docs.expo.dev/versions/latest/index.md

## Cursor Cloud specific instructions

- This folder is the Expo client. Install it with `npm ci` here, then run `npx expo start --web --host localhost --port 8082` and open `http://localhost:8082`. `--host localhost` listens on IPv6 `::1`, so use `localhost` rather than `127.0.0.1`.
- The screen talks to the hosted scout API. Do not submit a search against that production URL while testing the client. Filling the product field and choosing a budget preset is enough to show the form works.
- The API lives in the parent repository (`app.py`, `requirements.txt`, `_pipeline_check.py`). Create `.venv` with `python3 -m venv .venv` after `python3.12-venv` is installed, then `.venv/bin/pip install -r requirements.txt`.
- `app.py` refuses to import unless `OPENAI_API_KEY` is set. The deterministic check does not call OpenAI: `OPENAI_API_KEY=local-dev .venv/bin/python _pipeline_check.py`.
- A real `POST /api/scout` also needs `SERPER_API_KEY`. Without it the route returns HTTP 503 and does not invent prices. `TAVILY_API_KEY` is optional extra web search.
