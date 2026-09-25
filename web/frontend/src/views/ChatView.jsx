import { useRef, useState } from "react";
import { Send, Trash2 } from "lucide-react";
import { streamChat } from "../api";

export default function ChatView({ sessionId, userName, onSessionChange }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const messagesRef = useRef(null);

  function scrollToBottom() {
    requestAnimationFrame(() => {
      if (messagesRef.current) {
        messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
      }
    });
  }

  function appendMessage(content, role) {
    setMessages((current) => [...current, { content, role }]);
    scrollToBottom();
  }

  function deleteMessage(index) {
    setMessages((current) => current.filter((_, messageIndex) => messageIndex !== index));
  }

  async function submit() {
    const content = input.trim();
    if (!content || sending) return;
    const assistantIndex = messages.length + 1;
    setMessages((current) => [
      ...current,
      { content, role: "user" },
      { content: "", role: "assistant" }
    ]);
    scrollToBottom();
    setInput("");
    setSending(true);
    try {
      await streamChat(
        {
          message: content,
          session_id: sessionId,
          user_id: userName || "web-user"
        },
        {
          onChunk(text) {
            setMessages((current) =>
              current.map((message, index) =>
                index === assistantIndex
                  ? { ...message, content: message.content + text }
                  : message
              )
            );
            scrollToBottom();
          },
          onDone(data) {
            if (data.session_id) onSessionChange(data.session_id);
            const usage = data.usage || {};
            const model = data.model || "-";
            appendMessage(
              `模型 ${model} · 输入 ${usage.prompt_tokens || 0} · 输出 ${usage.completion_tokens || 0} · 总计 ${usage.total_tokens || 0}`,
              "meta"
            );
          },
          onError(message) {
            setMessages((current) => [
              ...current,
              { content: message, role: "error" }
            ]);
            scrollToBottom();
          }
        }
      );
    } catch (error) {
      appendMessage(error.message, "error");
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="view">
      <div className="chat-shell">
        <div className="messages" ref={messagesRef}>
          {messages.length === 0 && <div className="msg-hint">通过 Runtime 发送消息。</div>}
          {messages.map((message, index) => (
            <div className={`msg ${message.role}`} key={`${message.role}-${index}`}>
              <button
                className="icon-btn msg-delete"
                onClick={() => deleteMessage(index)}
                title="删除"
              >
                <Trash2 size={14} />
              </button>
              {message.content}
            </div>
          ))}
        </div>
        <div className="composer">
          <textarea
            rows="1"
            value={input}
            placeholder="输入消息，Enter 发送"
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                submit();
              }
            }}
          />
          <button className="btn primary" disabled={sending} onClick={submit}>
            <Send size={16} />
            发送
          </button>
        </div>
      </div>
    </div>
  );
}
