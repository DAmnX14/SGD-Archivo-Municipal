/** Compilar: npx tailwindcss -i static/css/tailwind.src.css -o static/css/tailwind.css --minify */
module.exports = {
  content: ["./templates/**/*.html", "./static/js/**/*.js"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        marino: "#0A367A", vivo: "#0056D2", celeste: "#EBF3FA", exito: "#10B981", peligro: "#EF4444",
        app: "var(--c-app)", surface: "var(--c-surface)", surface2: "var(--c-surface2)",
        borde: "var(--c-borde)", texto: "var(--c-texto)", muted: "var(--c-muted)",
      },
      borderRadius: { card: "12px" },
      fontFamily: { sans: ['"Segoe UI"', "system-ui", "-apple-system", "Roboto", "Arial", "sans-serif"] },
    },
  },
  plugins: [],
};
