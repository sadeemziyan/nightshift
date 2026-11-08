import { Spectrum } from "spectrum-ts";
import { imessage } from "spectrum-ts/providers/imessage";

const app = await Spectrum({ providers: [imessage.config()] });
for await (const [space, message] of app.messages) {
  if (message.content.type === "text") {
    await space.send("Nightshift test: this text came from our backend.");
  }
}