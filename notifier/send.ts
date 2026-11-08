// Send one iMessage through Photon Spectrum. Used by backend/api/notify.py.
// Reads NIGHTSHIFT_TO (phone, +1XXXXXXXXXX) and NIGHTSHIFT_MSG from the environment, not argv,
// so characters like ">" in a message can never be mangled by the shell.
import { Spectrum } from "spectrum-ts";
import { imessage } from "spectrum-ts/providers/imessage";

const to = process.env.NIGHTSHIFT_TO;
const text = process.env.NIGHTSHIFT_MSG;
if (!to || !text) {
  console.error("Need NIGHTSHIFT_TO and NIGHTSHIFT_MSG");
  process.exit(2);
}
if (!process.env.SPECTRUM_PROJECT_ID || !process.env.SPECTRUM_PROJECT_SECRET) {
  console.error("Missing SPECTRUM_PROJECT_ID or SPECTRUM_PROJECT_SECRET");
  process.exit(2);
}

const timer = setTimeout(() => {
  console.error("Timed out after 45 s");
  process.exit(3);
}, 45_000);

try {
  const app = await Spectrum({ providers: [imessage.config()] });
  const im = imessage(app);
  const user = await im.user(to);
  const dm = await im.space.create(user);
  await dm.send(text);
  console.log("SENT");
  clearTimeout(timer);
  process.exit(0);
} catch (err) {
  console.error("FAILED:", err instanceof Error ? err.message : err);
  process.exit(1);
}
