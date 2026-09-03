import { Headphones, Users, Wallet, type LucideIcon } from "lucide-react";

/* A blank instruction box is the hardest part of setting up an assistant.
   These three are starting points, not presets — the box stays editable. The
   wording itself lives in the dictionary (`assistants.template.<key>.text`)
   so a template fills the box in the interface language. */
export type TemplateKey = "helpdesk" | "finance" | "hr";

export const TEMPLATES: { key: TemplateKey; icon: LucideIcon }[] = [
  { key: "helpdesk", icon: Headphones },
  { key: "finance", icon: Wallet },
  { key: "hr", icon: Users },
];
