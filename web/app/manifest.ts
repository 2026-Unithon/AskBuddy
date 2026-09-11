import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "AskBuddy",
    short_name: "AskBuddy",
    description: "매장 업무 인수인계를 도와주는 Buddy",
    start_url: "/role",
    display: "standalone",
    background_color: "#f8fbf8",
    theme_color: "#2aa06a",
    icons: [
      {
        src: "/images/buddy-hero.png",
        sizes: "512x512",
        type: "image/png",
      },
    ],
  };
}
