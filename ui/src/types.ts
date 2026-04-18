export interface Transcript {
  user:      string
  ai:        string
  time:      string
  timestamp: number
}

export interface PollData {
  transcripts: Transcript[]
  processing:  boolean
  thinking:    boolean
  partial_ai:  string
  muted:       boolean
  updated:     number
}

export type Status = 'active' | 'processing' | 'thinking' | 'muted' | 'offline'
