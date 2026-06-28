// Resolve a public-folder asset against Vite's configured base path.
//
// import.meta.env.BASE_URL is "/" in dev + the Tauri desktop bundle, and "/pact/"
// for the GitHub Pages project site. Root-absolute string literals in runtime JS
// (src=, href=, CSS url() set from JS) are NOT rewritten by Vite, so they break
// under a subpath — route every public asset through this helper.
//
//   asset("/cards/x.svg") → "/cards/x.svg"      (base "/")
//   asset("/cards/x.svg") → "/pact/cards/x.svg" (base "/pact/")
export const asset = (p: string): string =>
  import.meta.env.BASE_URL.replace(/\/$/, "") + "/" + p.replace(/^\/+/, "");
