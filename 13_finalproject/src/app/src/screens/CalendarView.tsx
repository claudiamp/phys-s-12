import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { Calendar, DateData } from "react-native-calendars";

import { getEvents } from "../api";

const GREEN = "#2e7d32";

export default function CalendarView() {
  const [takenDates, setTakenDates] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchEvents = useCallback(async () => {
    setError(null);
    try {
      const events = await getEvents();
      setTakenDates(new Set(events.map((e) => e.date)));
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
    <ScrollView
      contentContainerStyle={styles.container}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
      }
    >
      <Text style={styles.title}>Calendar</Text>
      {error ? <Text style={styles.error}>{error}</Text> : null}
      {loading ? (
        <ActivityIndicator style={styles.loading} color={GREEN} />
      ) : (
        <Calendar
          dayComponent={(props: { date?: DateData; state?: string }) => {
            const { date, state } = props;
            // Only check real in-month days — not the greyed adjacent-month cells.
            const taken =
              !!date && state !== "disabled" && takenDates.has(date.dateString);
            return (
              <View style={styles.day}>
                <Text
                  style={[
                    styles.dayText,
                    state === "disabled" && styles.dayDisabled,
                  ]}
                >
                  {date?.day}
                </Text>
                {/* Green check under days a pill was taken (space keeps height stable). */}
                <Text style={styles.check}>{taken ? "✓" : " "}</Text>
              </View>
            );
          }}
        />
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { padding: 16, flexGrow: 1 },
  title: { fontSize: 22, fontWeight: "600", marginBottom: 12 },
  loading: { marginTop: 40 },
  error: { color: "#c62828", marginBottom: 12 },
  day: { alignItems: "center", justifyContent: "center", height: 40 },
  dayText: { fontSize: 16 },
  dayDisabled: { color: "#c0c0c0" },
  check: { color: GREEN, fontSize: 14, fontWeight: "700", lineHeight: 16 },
});
