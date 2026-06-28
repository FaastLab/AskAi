import { useEffect, useRef, useState } from "react";
import { getRealtimeSession, searchChunks } from "../lib/api";

/**
 * Live, full-duplex voice via the OpenAI Realtime API over WebRTC.
 *
 * Flow: mint an ephemeral session (server-side) → WebRTC handshake straight to
 * OpenAI → server-VAD turn-taking (hands-free, no push-to-talk) → the model
 * calls our `search_documents` tool, which we run against /v1/search and feed
 * back, so spoken answers are GROUNDED in the corpus. The role's prompt drives
 * the persona + self-introduction.
 *
 * Note: requires HTTPS (getUserMedia) — fine behind the demo's TLS.
 */
type Line = { who: "you" | "agent"; text: string };

export function RealtimeVoice({
  role,
  roleLabel,
  onClose,
}: {
  role: string | null;
  roleLabel: string;
  onClose: () => void;
}) {
  const [status, setStatus] = useState<
    "connecting" | "live" | "error" | "ended"
  >("connecting");
  const [error, setError] = useState<string | null>(null);
  const [lines, setLines] = useState<Line[]>([]);

  const pcRef = useRef<RTCPeerConnection | null>(null);
  const dcRef = useRef<RTCDataChannel | null>(null);
  const micRef = useRef<MediaStream | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  // Accumulates the agent's in-progress spoken transcript for the current turn.
  const agentBufRef = useRef<string>("");

  // Tear everything down on unmount / End.
  function hangup() {
    try {
      dcRef.current?.close();
      pcRef.current?.getSenders().forEach((s) => s.track?.stop());
      pcRef.current?.close();
      micRef.current?.getTracks().forEach((t) => t.stop());
    } catch {
      /* ignore */
    }
    pcRef.current = null;
    dcRef.current = null;
    micRef.current = null;
  }

  // The model called search_documents → run it against the corpus and feed the
  // passages back so the spoken answer is grounded.
  async function runSearchTool(callId: string, argsJson: string) {
    let query = "";
    try {
      query = (JSON.parse(argsJson || "{}").query as string) || "";
    } catch {
      /* ignore */
    }
    let output = "No relevant passages found.";
    if (query) {
      const res = await searchChunks(query, { k: 6, rerank: false });
      const hits = res?.hits ?? [];
      if (hits.length) {
        output = hits
          .slice(0, 6)
          .map(
            (h, i) =>
              `[${i + 1}] ${h.document_title}: ${String(h.content).slice(0, 600)}`,
          )
          .join("\n\n");
      }
    }
    const dc = dcRef.current;
    if (!dc || dc.readyState !== "open") return;
    dc.send(
      JSON.stringify({
        type: "conversation.item.create",
        item: { type: "function_call_output", call_id: callId, output },
      }),
    );
    dc.send(JSON.stringify({ type: "response.create" }));
  }

  function onEvent(raw: string) {
    let msg: Record<string, unknown>;
    try {
      msg = JSON.parse(raw);
    } catch {
      return;
    }
    const type = msg.type as string;
    if (type === "response.audio_transcript.delta") {
      agentBufRef.current += (msg.delta as string) || "";
    } else if (type === "response.audio_transcript.done") {
      const text = (msg.transcript as string) || agentBufRef.current;
      agentBufRef.current = "";
      if (text.trim()) setLines((p) => [...p, { who: "agent", text: text.trim() }]);
    } else if (
      type === "conversation.item.input_audio_transcription.completed"
    ) {
      const text = (msg.transcript as string) || "";
      if (text.trim()) setLines((p) => [...p, { who: "you", text: text.trim() }]);
    } else if (type === "response.done") {
      // Execute any function calls the model emitted this turn.
      const resp = (msg.response as Record<string, unknown>) || {};
      const output = (resp.output as Array<Record<string, unknown>>) || [];
      for (const item of output) {
        if (item.type === "function_call" && item.name === "search_documents") {
          void runSearchTool(item.call_id as string, item.arguments as string);
        }
      }
    } else if (type === "error") {
      const err = (msg.error as Record<string, unknown>) || {};
      setError((err.message as string) || "Realtime error.");
    }
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const session = await getRealtimeSession(role);
        const ephemeral = session?.client_secret?.value;
        if (!ephemeral) throw new Error("Could not start a voice session.");
        const model = session?.model || "gpt-4o-realtime-preview-2024-12-17";

        const pc = new RTCPeerConnection();
        pcRef.current = pc;

        // Remote audio (the agent's voice).
        const audio = new Audio();
        audio.autoplay = true;
        audioRef.current = audio;
        pc.ontrack = (e) => {
          audio.srcObject = e.streams[0];
        };

        // Mic.
        const mic = await navigator.mediaDevices.getUserMedia({ audio: true });
        if (cancelled) {
          mic.getTracks().forEach((t) => t.stop());
          return;
        }
        micRef.current = mic;
        pc.addTrack(mic.getTracks()[0], mic);

        // Events channel.
        const dc = pc.createDataChannel("oai-events");
        dcRef.current = dc;
        dc.onmessage = (e) => onEvent(e.data);
        dc.onopen = () => {
          setStatus("live");
          // Nudge the agent to greet + introduce itself first.
          dc.send(JSON.stringify({ type: "response.create" }));
        };

        // SDP handshake with OpenAI Realtime.
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        const sdpResp = await fetch(
          `https://api.openai.com/v1/realtime?model=${encodeURIComponent(model)}`,
          {
            method: "POST",
            body: offer.sdp,
            headers: {
              Authorization: `Bearer ${ephemeral}`,
              "Content-Type": "application/sdp",
              "OpenAI-Beta": "realtime=v1",
            },
          },
        );
        if (!sdpResp.ok) throw new Error(`Voice connect failed (${sdpResp.status}).`);
        const answerSdp = await sdpResp.text();
        if (cancelled) return;
        await pc.setRemoteDescription({ type: "answer", sdp: answerSdp });
      } catch (e) {
        if (cancelled) return;
        setError((e as Error).message || "Could not start voice.");
        setStatus("error");
      }
    })();

    return () => {
      cancelled = true;
      hangup();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function end() {
    hangup();
    setStatus("ended");
    onClose();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-lg rounded-lg bg-white shadow-xl flex flex-col max-h-[80vh]">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold text-ink-900">Live voice</h2>
            <p className="text-xs text-ink-500">
              {roleLabel} ·{" "}
              {status === "connecting"
                ? "connecting…"
                : status === "live"
                  ? "listening — just talk"
                  : status === "error"
                    ? "error"
                    : "ended"}
            </p>
          </div>
          <span
            className={
              "inline-block h-3 w-3 rounded-full " +
              (status === "live"
                ? "bg-emerald-500 animate-pulse"
                : status === "error"
                  ? "bg-red-500"
                  : "bg-slate-300")
            }
          />
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-2">
          {lines.length === 0 && !error && (
            <p className="text-sm text-ink-400">
              {status === "live"
                ? "Say hello — the assistant will introduce itself and answer from your documents."
                : "Starting the voice session…"}
            </p>
          )}
          {lines.map((l, i) => (
            <div key={i} className={l.who === "you" ? "text-right" : "text-left"}>
              <span
                className={
                  "inline-block rounded-lg px-3 py-1.5 text-sm " +
                  (l.who === "you"
                    ? "bg-ink-900 text-white"
                    : "bg-slate-100 text-ink-800")
                }
              >
                {l.text}
              </span>
            </div>
          ))}
          {error && <p className="text-sm text-red-700">{error}</p>}
        </div>

        <div className="border-t border-slate-200 px-4 py-3 flex justify-end">
          <button
            onClick={end}
            className="rounded-md bg-red-600 px-4 py-2 text-sm text-white hover:bg-red-700"
          >
            End call
          </button>
        </div>
      </div>
    </div>
  );
}
