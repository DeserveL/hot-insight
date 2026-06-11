import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        surface: "#f5f5f7",
        ink: "#1d1d1f",
        muted: "#6e6e73",
        line: "#d2d2d7",
        bao: "#ef4444",
        fei: "#f97316",
        re: "#f59e0b",
      },
      boxShadow: {
        soft: "0 18px 60px rgba(0, 0, 0, 0.08)",
      },
      borderRadius: {
        card: "8px",
      },
    },
  },
  plugins: [],
};

export default config;
