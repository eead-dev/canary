// Packaging only: copy verified source artifacts; never compute CAN evidence.
import { readFile, mkdir, copyFile } from "node:fs/promises";
import { createHash } from "node:crypto";
// scripts/ is inside frontend/, so resolve the repository sibling explicitly.
const evidence = new URL("../../examples/comma2k19/evidence/", import.meta.url);
const destination = new URL("../public/evidence/", import.meta.url);
const manifest = JSON.parse(
  await readFile(new URL("manifest.json", evidence), "utf8"),
);
await mkdir(destination, { recursive: true });
for (const artifact of manifest.artifacts) {
  if (!/^[\w.-]+$/.test(artifact.filename))
    throw new Error("Unsafe evidence filename");
  const bytes = await readFile(new URL(artifact.filename, evidence));
  if (createHash("sha256").update(bytes).digest("hex") !== artifact.sha256)
    throw new Error(`Evidence checksum mismatch: ${artifact.filename}`);
  await copyFile(
    new URL(artifact.filename, evidence),
    new URL(artifact.filename, destination),
  );
}
await copyFile(
  new URL("manifest.json", evidence),
  new URL("manifest.json", destination),
);
console.log(
  `Verified and packaged ${manifest.artifacts.length} curated artifacts.`,
);
