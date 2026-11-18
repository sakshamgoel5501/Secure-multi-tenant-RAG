export type Citation = {
  marker: string;
  chunk_id: string;
  document_id: string;
  version: number;
  title: string;
  section: string | null;
  start_offset: number;
  end_offset: number;
};

export type AskData = {
  answer: string;
  grounded: boolean;
  degraded: string[];
  citations: Citation[];
};

export type Passage = {
  chunk_id: string;
  document_id: string;
  version: number;
  title: string;
  text: string;
  start_offset: number;
  end_offset: number;
};

export type AskResult = {
  data: AskData;
  passages: Passage[];
  timing: Record<string, number>;
};


