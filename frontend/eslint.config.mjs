import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
  {
    rules: {
      // These patterns are common in data-fetching effects; the new React 19
      // rule flags them as errors, but they are intentional in this codebase.
      // Downgrade to warning so build is not blocked, and fix incrementally.
      "react-hooks/set-state-in-effect": "warn",
      // Allow explicit any in a few places where the backend schema is dynamic
      "@typescript-eslint/no-explicit-any": "warn",
      // Unescaped entities are cosmetic; don't block build
      "react/no-unescaped-entities": "warn",
    },
  },
]);

export default eslintConfig;
