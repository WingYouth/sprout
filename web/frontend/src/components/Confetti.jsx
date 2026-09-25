import { useEffect } from "react";

export default function Confetti({ burstKey }) {
  useEffect(() => {
    if (!burstKey) return;
    const colors = ["#8b5cf6", "#f59e0b", "#10b981", "#f472b6", "#60a5fa"];
    for (let index = 0; index < 36; index += 1) {
      const piece = document.createElement("span");
      piece.className = "confetti-piece";
      piece.style.background = colors[index % colors.length];
      piece.style.left = `${window.innerWidth / 2}px`;
      piece.style.top = `${window.innerHeight / 2}px`;
      document.body.appendChild(piece);
      const dx = (Math.random() - 0.5) * 360;
      const dy = (Math.random() - 0.75) * 340;
      const rotation = Math.random() * 720 - 360;
      piece.animate(
        [
          { transform: "translate(0, 0) rotate(0deg)", opacity: 1 },
          { transform: `translate(${dx}px, ${dy}px) rotate(${rotation}deg)`, opacity: 0 }
        ],
        {
          duration: 850 + Math.random() * 450,
          easing: "cubic-bezier(.15,.8,.35,1)"
        }
      ).onfinish = () => piece.remove();
    }
  }, [burstKey]);

  return null;
}
