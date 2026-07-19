import React, { useCallback, useEffect, useState } from "react";
import {
  FlatList,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { getEvents } from "../api";
import { PillEvent } from "../types";

export default function HistoryView() {
  const [events, setEvents] = useState<PillEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchEvents = useCallback(async () => {
    setError(null);
    try {
      const data = await getEvents();
      // Show most recent first (server returns ascending).
      const sorted = [...data].sort((a, b) => (a.date < b.date ? 1 : -1));
      setEvents(sorted);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load events");
    }
  }, []);

  useEffect(() => {
    fetchEvents().finally(() => setLoading(false));
  }, [fetchEvents]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await fetchEvents();
    setRefreshing(false);
  }, [fetchEvents]);

  return (
    <View style={styles.container}>
      <Text style={styles.title}>History</Text>
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <FlatList
        data={events}
        keyExtractor={(item) => item.date}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
        }
        ListEmptyComponent={
          !loading ? (
            <Text style={styles.empty}>No pills recorded yet.</Text>
          ) : null
        }
        renderItem={({ item }) => (
          <View style={styles.row}>
            <Text style={styles.date}>{formatDate(item.takenAt)}</Text>
            <Text style={styles.time}>{item.takenAt.slice(11, 16)}</Text>
          </View>
        )}
      />
    </View>
  );
}

// e.g. "Fri, Jul 10 2026". takenAt is local time with no tz suffix, so
// `new Date(...)` parses it as local and avoids a UTC-midnight off-by-one.
function formatDate(value: string): string {
  const d = new Date(value);
  return d.toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 16 },
  title: { fontSize: 22, fontWeight: "600", marginBottom: 12 },
  error: { color: "#c62828", marginBottom: 12 },
  empty: { color: "#888", marginTop: 24, textAlign: "center" },
  row: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingVertical: 14,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: "#e0e0e0",
  },
  date: { fontSize: 16 },
  time: { fontSize: 16, fontWeight: "600", color: "#2e7d32" },
});
