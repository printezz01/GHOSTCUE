/**
 * agent/alert-dispatcher.js — Broadcasts nudges to all connected clients
 * 
 * Receives alerts from the analyzers and dispatches them via WebSocket
 * to all connected interfaces (Terminal, Telegram bot, WhatsApp bot).
 * 
 * Alert format:
 * {
 *   type: "pressure_point" | "contradiction" | "coverage_gap",
 *   message: "Ask about scope of the project",  // max 12 words per SOUL.md
 *   evidence: "Candidate said X but resume claims Y",  // optional
 *   severity: "low" | "medium" | "high",
 *   timestamp: "2024-01-15T10:30:00Z"
 * }
 */

// Reference to the WebSocket server — set by index.js on boot
let wss = null;

// Alert history for the current session (for deduplication)
let alertHistory = [];

/**
 * Register the WebSocket server instance.
 * Called once by index.js during startup.
 */
export function setWebSocketServer(wsServer) {
  wss = wsServer;
}

/**
 * Broadcast an alert to all connected WebSocket clients.
 * Deduplicates identical alerts within a 30-second window.
 * 
 * @param {object} alert — alert object from an analyzer
 */
export function dispatch(alert) {
  // Add timestamp if missing
  if (!alert.timestamp) {
    alert.timestamp = new Date().toISOString();
  }

  // Deduplication: skip if same message was sent in last 30 seconds
  const now = Date.now();
  const isDuplicate = alertHistory.some(
    prev => prev.message === alert.message && (now - prev.time) < 30000
  );

  if (isDuplicate) {
    return;
  }

  // Track for deduplication
  alertHistory.push({ message: alert.message, time: now });

  // Clean old entries (keep last 60 seconds)
  alertHistory = alertHistory.filter(a => (now - a.time) < 60000);

  // Log to console (always — even if no clients connected)
  const icon = {
    pressure_point: '[PROBE]',
    contradiction: '[CONFLICT]',
    coverage_gap: '[GAP]'
  }[alert.type] || '[ALERT]';

  console.log(`${icon} ${alert.message}`);
  if (alert.evidence) {
    console.log(`        Evidence: ${alert.evidence}`);
  }

  // Broadcast via WebSocket
  if (wss && wss.clients) {
    const payload = JSON.stringify({
      event: 'alert',
      data: alert
    });

    let sentCount = 0;
    wss.clients.forEach(client => {
      // WebSocket.OPEN = 1
      if (client.readyState === 1) {
        client.send(payload);
        sentCount++;
      }
    });

    if (sentCount > 0) {
      console.log(`        Sent to ${sentCount} client(s)`);
    }
  }
}

/**
 * Broadcast a system event (not an alert — informational messages).
 * Used for session start, session end, report ready, etc.
 */
export function broadcastEvent(eventType, data) {
  if (!wss || !wss.clients) return;

  const payload = JSON.stringify({
    event: eventType,
    data: {
      ...data,
      timestamp: new Date().toISOString()
    }
  });

  wss.clients.forEach(client => {
    if (client.readyState === 1) {
      client.send(payload);
    }
  });
}

/**
 * Get alert history for the current session.
 * Used by the report generator to include alerts in the PDF.
 */
export function getAlertHistory() {
  return alertHistory.map(a => ({
    message: a.message,
    timestamp: new Date(a.time).toISOString()
  }));
}

/**
 * Clear alert history (called on session end).
 */
export function clearHistory() {
  alertHistory = [];
}
