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
        surface: "#F5F5F7",
        ink: "#1D1D1F",
        muted: "#86868B",
        line: "#D2D2D7",
        bao: "#A55A2A",
        fei: "#9A6A35",
        re: "#9B7A2F",
      },
      boxShadow: {
        apple: "0 4px 24px rgba(0, 0, 0, 0.04)",
        "apple-lg": "0 18px 50px rgba(0, 0, 0, 0.08)",
        soft: "0 4px 24px rgba(0, 0, 0, 0.04)",
      },
      borderRadius: {
        card: "24px",
      },
    },
  },
  plugins: [],
};

export default config;
