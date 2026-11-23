// The Security demo needs a query that reliably finds a given document. This mirrors how the synthetic 
// corpus names its projects, so it only works with that corpus.

const ADJ = ["amber", "brisk", "cobalt", "dusky", "ember", "frost", "golden", "hollow"];
const NOUN = ["falcon", "harbor", "lantern", "meadow", "nebula", "orchard", "pylon", "quartz"];

/** "t1-doc-0007" -> "Project dusky-falcon-7" (demo corpus only) */
export function queryForDoc(documentId: string): string {
  const m = documentId.match(/-(\d+)$/);
  if (!m) return documentId;
  const i = Number(m[1]);
  return `Project ${ADJ[i % ADJ.length]}-${NOUN[Math.floor(i / ADJ.length) % NOUN.length]}-${i}`;
}


export const isCorpusDoc = (id: string) => /^t\d+-doc-\d+$/.test(id);

