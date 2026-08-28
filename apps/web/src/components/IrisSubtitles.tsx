import React, { useEffect, useMemo, useRef, useState } from "react";
import type { ChatMessage, VoiceState } from "../types";
import { animateThinkingWave } from "../animations/transitions";

/**
 * Splits text into readable subtitle cues (1-2 sentences / max ~75-85 characters),
 * cleanly splitting on newlines, sentence boundaries, punctuation pauses, or word boundaries.
 */
export function splitIntoSubtitleCues(text: string, maxChars = 80): string[] {
  if (!text || !text.trim()) return [];
  const normalized = text.trim();

  // 1. Split into paragraphs/lines first (always respect explicit line breaks)
  const rawParagraphs = normalized.split(/\n+/);
  const cues: string[] = [];

  for (const para of rawParagraphs) {
    const p = para.trim();
    if (!p) continue;

    if (p.length <= maxChars) {
      cues.push(p);
      continue;
    }

    const sentenceRegex = /[^.!?…]+(?:[.!?…]+(?:\s+|$)|$)/g;
    const rawSentences = p.match(sentenceRegex) || [p];

    let currentChunk = "";

    for (const rawSentence of rawSentences) {
      const sentence = rawSentence.trim();
      if (!sentence) continue;

      if (sentence.length <= maxChars) {
        if (!currentChunk) {
          currentChunk = sentence;
        } else if (currentChunk.length + 1 + sentence.length <= maxChars) {
          currentChunk += " " + sentence;
        } else {
          cues.push(currentChunk);
          currentChunk = sentence;
        }
        continue;
      }

      if (currentChunk) {
        cues.push(currentChunk);
        currentChunk = "";
      }

      const clauseRegex = /[^,;:—–]+(?:[,;:—–]+(?:\s+|$)|$)/g;
      const rawClauses = sentence.match(clauseRegex) || [sentence];

      for (const rawClause of rawClauses) {
        const clause = rawClause.trim();
        if (!clause) continue;

        if (clause.length <= maxChars) {
          if (!currentChunk) {
            currentChunk = clause;
          } else if (currentChunk.length + 1 + clause.length <= maxChars) {
            currentChunk += " " + clause;
          } else {
            cues.push(currentChunk);
            currentChunk = clause;
          }
          continue;
        }

        if (currentChunk) {
          cues.push(currentChunk);
          currentChunk = "";
        }

        const words = clause.split(/\s+/);
        for (const word of words) {
          if (!word) continue;
          if (!currentChunk) {
            currentChunk = word;
          } else if (currentChunk.length + 1 + word.length <= maxChars) {
            currentChunk += " " + word;
          } else {
            cues.push(currentChunk);
            currentChunk = word;
          }
        }
      }
    }

    if (currentChunk) {
      cues.push(currentChunk);
      currentChunk = "";
    }
  }

  return cues.filter((cue) => cue.trim().length > 0);
}

export interface IrisSubtitlesProps {
  messages: ChatMessage[];
  loading: boolean;
  voiceState: VoiceState;
  activeAudio?: HTMLAudioElement | null;
  livePlaybackSegment?: string;
  onOpenMemory?: () => void;
  containerRef?: React.RefObject<HTMLDivElement | null>;
}

export function IrisSubtitles({
  messages,
  loading,
  voiceState,
  activeAudio,
  livePlaybackSegment,
  containerRef,
}: IrisSubtitlesProps) {
  const thinkingRef = useRef<HTMLDivElement | null>(null);

  // Find the latest assistant message
  const assistantMessages = useMemo(
    () => messages.filter((m) => m.role === "assistant"),
    [messages],
  );
  const latestAssistantMessage = assistantMessages[assistantMessages.length - 1];
  const messageContent = latestAssistantMessage?.content || "";
  const messageId = latestAssistantMessage?.id || "";
  const ttsStatus = latestAssistantMessage?.ttsStatus;
  const hasVoicePending = latestAssistantMessage?.voiceRequestId && (ttsStatus === "queued" || ttsStatus === undefined);

  // Split the latest message into subtitle cues
  const cues = useMemo(
    () => splitIntoSubtitleCues(messageContent),
    [messageContent],
  );

  // Core synchronization state
  const isInitialMountRef = useRef(true);
  const [activeCueIndex, setActiveCueIndex] = useState(() => (cues.length > 0 ? cues.length - 1 : 0));
  const [targetCueIndex, setTargetCueIndex] = useState(() => (cues.length > 0 ? cues.length - 1 : 0));
  const lastMessageIdRef = useRef<string>(messageId);

  // Thinking wave animation
  useEffect(() => {
    if (loading && thinkingRef.current) {
      const dots = thinkingRef.current.querySelectorAll<HTMLElement>("span");
      const anim = animateThinkingWave(dots);
      return () => {
        anim?.cancel();
      };
    }
  }, [loading]);

  // Handle new message arrival
  useEffect(() => {
    if (isInitialMountRef.current) {
      isInitialMountRef.current = false;
      lastMessageIdRef.current = messageId;
      const endIdx = cues.length > 0 ? cues.length - 1 : 0;
      setActiveCueIndex(endIdx);
      setTargetCueIndex(endIdx);
      return;
    }

    if (messageId && messageId !== lastMessageIdRef.current) {
      lastMessageIdRef.current = messageId;
      setActiveCueIndex(0);
      setTargetCueIndex(0);
    }
  }, [messageId, cues.length]);

  // 1. Calculate Target Index (Live TTS & Silent Pacing)
  useEffect(() => {
    if (activeAudio) return; // HTML5 Audio controls exact index directly below

    if (voiceState === "speaking" && livePlaybackSegment) {
      const fullText = cues.join(" ");
      const segText = livePlaybackSegment.trim();
      if (!segText) return;

      // Find where this spoken segment is in the full text
      const startPos = fullText.indexOf(segText.substring(0, Math.min(30, segText.length)));
      if (startPos >= 0) {
        const endPos = startPos + segText.length;
        let charsSoFar = 0;
        let matchedEndIndex = 0;
        
        for (let i = 0; i < cues.length; i++) {
          charsSoFar += cues[i].length + 1; // +1 for assumed space
          // generous margin for punctuation
          if (charsSoFar >= endPos - 15) {
            matchedEndIndex = i;
            break;
          }
        }
        // Only ever move the target forward
        setTargetCueIndex(prev => Math.max(prev, matchedEndIndex));
      }
    } else if (voiceState === "idle" && !loading && !hasVoicePending) {
      // In completely silent mode (or stream finished), target the very end
      setTargetCueIndex(cues.length > 0 ? cues.length - 1 : 0);
    }
  }, [livePlaybackSegment, voiceState, loading, hasVoicePending, cues, activeAudio]);

  // 2. Smooth Auto-Advancer (Chases the target index)
  useEffect(() => {
    if (activeAudio) return; // Audio has its own continuous updates

    if (activeCueIndex < targetCueIndex && activeCueIndex < cues.length - 1) {
      const currentCue = cues[activeCueIndex] || "";
      // Calculate comfortable reading time: ~60ms per character.
      // Clamped between 1.2s and 4s so it doesn't rush or stall.
      const delayMs = Math.max(1200, Math.min(4000, currentCue.length * 60));

      const timer = setTimeout(() => {
        setActiveCueIndex(prev => prev + 1);
      }, delayMs);

      return () => clearTimeout(timer);
    }
  }, [activeCueIndex, targetCueIndex, cues, activeAudio]);

  // 3. HTML5 Audio Sync (REST Mode)
  useEffect(() => {
    if (!activeAudio || cues.length <= 1) return;

    const handleTimeUpdate = () => {
      if (!activeAudio.duration || isNaN(activeAudio.duration) || activeAudio.duration <= 0) return;
      const progress = Math.min(1, Math.max(0, activeAudio.currentTime / activeAudio.duration));

      const totalChars = cues.reduce((sum, c) => sum + c.length, 0);
      let cumulative = 0;
      let target = cues.length - 1;

      for (let i = 0; i < cues.length; i++) {
        cumulative += cues[i].length;
        if (progress <= cumulative / totalChars) {
          target = i;
          break;
        }
      }
      
      setActiveCueIndex(target);
    };

    const handleEnded = () => {
      setActiveCueIndex(cues.length > 0 ? cues.length - 1 : 0);
    };

    activeAudio.addEventListener("timeupdate", handleTimeUpdate);
    activeAudio.addEventListener("loadedmetadata", handleTimeUpdate);
    activeAudio.addEventListener("play", handleTimeUpdate);
    activeAudio.addEventListener("ended", handleEnded);

    handleTimeUpdate();

    return () => {
      activeAudio.removeEventListener("timeupdate", handleTimeUpdate);
      activeAudio.removeEventListener("loadedmetadata", handleTimeUpdate);
      activeAudio.removeEventListener("play", handleTimeUpdate);
      activeAudio.removeEventListener("ended", handleEnded);
    };
  }, [activeAudio, cues]);

  // Build the visible cue stack
  const MAX_VISIBLE_CUES = 2;
  const effectiveIndex = Math.min(Math.max(0, activeCueIndex), Math.max(0, cues.length - 1));

  const visibleCues: { text: string; index: number; key: string; age: number }[] = [];

  if (cues.length > 0) {
    const startIdx = Math.max(0, effectiveIndex - MAX_VISIBLE_CUES + 1);
    for (let i = startIdx; i <= effectiveIndex && i < cues.length; i++) {
      visibleCues.push({
        text: cues[i],
        index: i,
        key: `cue-${messageId}-${i}`,
        age: effectiveIndex - i,
      });
    }
  }

  return (
    <div className="message-list subtitles-mode" ref={containerRef} role="region" aria-label="Субтитры Iris">
      <div className="subtitles-viewport">
        {visibleCues.map((cue) => {
          const isActive = cue.age === 0;
          const ageClass = isActive
            ? "is-latest is-active-cue"
            : cue.age === 1
              ? "is-previous is-fading-cue"
              : "is-older";

          return (
            <article
              key={cue.key}
              className={`message assistant subtitle-cue ${ageClass}`}
            >
              <p data-i18n-skip>{cue.text}</p>
            </article>
          );
        })}

        {latestAssistantMessage?.ttsError && (
          <div className="message-error" data-i18n-skip>
            {latestAssistantMessage.ttsError}
          </div>
        )}

        {loading && (
          <div className="assistant-thinking subtitle-status" ref={thinkingRef} role="status">
            <span></span>
            <span></span>
            <span></span>
            <span className="thinking-text">Думаю . . .</span>
          </div>
        )}

        {!loading && voiceState === "recording" && (
          <div className="chat-subtitle-status subtitle-status">Слушаю . . .</div>
        )}

        {!loading && voiceState === "transcribing" && (
          <div className="chat-subtitle-status subtitle-status">Распознаю . . .</div>
        )}
      </div>
    </div>
  );
}
