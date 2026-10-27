import { Disclosure } from "./Disclosure";
import { useId, useMemo } from "react";

export type PatchFile = { name: string; patch: string; added: number; removed: number };

export function splitPatch(patch: string): PatchFile[] {
  const chunks = patch.replace(/\r\n/g, "\n").split(/(?=^diff --git )/m).filter(value => value.trim());
  return chunks.map((chunk, index) => {
    const lines = chunk.split("\n");
    const target = lines.find(line => line.startsWith("+++ ") && line !== "+++ /dev/null")?.slice(4);
    const original = lines.find(line => line.startsWith("--- "))?.slice(4);
    const header = /^diff --git (?:".*?"|\S+) (.+)$/m.exec(chunk)?.[1];
    const name = (target || original || header || `Изменения ${index + 1}`).replace(/^"|"$/g, "").replace(/^[ab]\//, "");
    return { name, patch: chunk, added: lines.filter(line => line.startsWith("+") && !line.startsWith("+++ ")).length,
      removed: lines.filter(line => line.startsWith("-") && !line.startsWith("--- ")).length };
  });
}

export function PatchReview({ patch }: { patch: string }) {
  const files = useMemo(() => splitPatch(patch), [patch]);
  const id = useId();
  return <section className="patch-review" aria-label="Изменения по файлам">
    <nav className="patch-file-list" aria-label="Изменённые файлы">
      {files.map((file, index) => <a key={index} href={`#${id}-${index}`}><span data-i18n-skip>{file.name}</span><small>+{file.added} −{file.removed}</small></a>)}
    </nav>
    {files.map((file, index) => <Disclosure materialKey={`patch.file.${file.name}`} label={<><span data-i18n-skip>{file.name}</span><small>+{file.added} −{file.removed}</small></>} className="patch-file" key={index} id={`${id}-${index}`} defaultOpen={files.length === 1 && file.patch.length < 200_000}>

      <pre tabIndex={0} aria-label={`Diff: ${file.name}`}>{file.patch.length > 200_000 ? file.patch : file.patch.split("\n").map((line, n) => <span key={n} className={line.startsWith("@@") ? "patch-hunk" : line.startsWith("+") && !line.startsWith("+++") ? "patch-added" : line.startsWith("-") && !line.startsWith("---") ? "patch-removed" : undefined}>{line}{"\n"}</span>)}</pre>
    </Disclosure>)}
  </section>;
}
