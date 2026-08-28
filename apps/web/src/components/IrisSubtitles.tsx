import React, { useEffect, useMemo, useRef, useState } from "react";
import type { ChatMessage, VoiceState } from "../types";
import { animateThinkingWave } from "../animations/transitions";

/**
 * Splits text into readable subtitle cues (1-2 sentences / max ~75-85 characters),
 * cleanly splitting on newlines, sentence boundaries, punctuation pauses, or word boundaries.
 */
export function splitIntoSubtitleCues(text: string, maxChars = 45): string[] {
  if (!text || !text.trim()) return [];
  const normalized = text.trim();

  const cues: string[] = [];
  const rawParagraphs = normalized.split(/\n+/);

  const hasSegmenter = typeof Intl !== "undefined" && "Segmenter" in Intl;
  const sentenceSegmenter = hasSegmenter
    ? new Intl.Segmenter("ru", { granularity: "sentence" })
    : null;

  for (const para of rawParagraphs) {
    const p = para.trim();
    if (!p) continue;

    if (p.length <= maxChars) {
      cues.push(p);
      continue;
    }

    let sentences: string[] = [];
    if (sentenceSegmenter) {
      sentences = Array.from(sentenceSegmenter.segment(p))
        .map((s) => s.segment.trim())
        .filter(Boolean);
    } else {
      sentences = (p.match(/[^.!?…]+(?:[.!?…]+(?:\s+|$)|$)/g) || [p])
        .map((s) => s.trim())
        .filter(Boolean);
    }

    let currentChunk = "";

    for (const sentence of sentences) {
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

      const clauses = (sentence.match(/[^,;:—–]+(?:[,;:—–]+(?:\s+|$)|$)/g) || [sentence])
        .map((c) => c.trim())
        .filter(Boolean);

      for (const clause of clauses) {
        if (clause.length <= maxChars) {
          if (!currentChunk) {
            currentChunk = clause;
          } else if (currentChunk.length + 1 + clause.length <= maxChars) {
            currentChunk += " " + clause;
          } else {
            cues.push(currentChunk);
            currentChunk = clause;
          }
        } else {
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
    }

    if (currentChunk) {
      cues.push(currentChunk);
    }
  }

  return cues;
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
      // Calculate comfortable reading time.
      // Base time per cue + ~50ms per character. Bonus time if it ends with punctuation.
      const hasPunctuation = /[.,:!?…]$/.test(currentCue.trim());
      const punctuationBonus = hasPunctuation ? 400 : 0;
      const baseDelay = 500;
      const charDelay = currentCue.length * 50;
      
      const calculatedDelayMs = baseDelay + charDelay + punctuationBonus;
      // Clamped to at least 1.2s, without a hard upper limit so long cues aren't rushed.
      const delayMs = Math.max(1200, calculatedDelayMs);

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

      const getCueWeight = (cue: string) => {
        const hasPunctuation = /[.,:!?…]$/.test(cue.trim());
        return cue.length + (hasPunctuation ? 8 : 0);
      };

      const totalWeight = cues.reduce((sum, c) => sum + getCueWeight(c), 0);
      let cumulative = 0;
      let target = cues.length - 1;

      for (let i = 0; i < cues.length; i++) {
        cumulative += getCueWeight(cues[i]);
        if (progress <= cumulative / totalWeight) {
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
    
    // Pad with empty cues so we ALWAYS render exactly MAX_VISIBLE_CUES elements
    const actualCuesCount = effectiveIndex - startIdx + 1;
    const missingCount = MAX_VISIBLE_CUES - actualCuesCount;
    
    for (let i = 0; i < missingCount; i++) {
      visibleCues.push({
        text: "\u00A0",
        index: -100 - i,
        key: `empty-${messageId}-${i}`,
        age: MAX_VISIBLE_CUES - 1 - i,
      });
    }

    for (let i = startIdx; i <= effectiveIndex && i < cues.length; i++) {
      visibleCues.push({
        text: cues[i],
        index: i,
        key: `cue-${messageId}-${i}`,
        age: effectiveIndex - i,
      });
    }
  } else {
    for (let i = 0; i < MAX_VISIBLE_CUES; i++) {
      visibleCues.push({
        text: "\u00A0",
        index: -100 - i,
        key: `empty-no-cues-${i}`,
        age: MAX_VISIBLE_CUES - 1 - i,
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
