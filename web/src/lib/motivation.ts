export const MOTIVATION: readonly string[] = [
  "Showing up is the whole game.",
  "The streak is the reward.",
  "Future-you is watching.",
  "Small reps, big proof.",
  "You signed it — now live it.",
  "Discipline is just love for future-you.",
  "One honest day at a time.",
  "The hard part was starting. You already did.",
  "Keep the promise small and the streak long.",
  "Proof beats intention.",
  "Don't break the chain.",
  "Your word's on the line — make it good.",
  "Momentum is built, not found.",
  "A pact kept is a self respected.",
  "Today's rep is tomorrow's identity.",
  "Quiet consistency wins.",
  "You're closer than the doubt says.",
  "Earn the streak. Keep the stake.",
  "The deadline is a gift — use it.",
  "Be the kind of person who follows through.",
];

export function pickStatement(seed: number = Math.random()): string {
  const i = Math.min(MOTIVATION.length - 1, Math.max(0, Math.floor(seed * MOTIVATION.length)));
  return MOTIVATION[i];
}
