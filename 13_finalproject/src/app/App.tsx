import React, { useEffect, useState } from "react";
import {
  SafeAreaView,
  StatusBar,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";

import CalendarView from "./src/screens/CalendarView";
import HistoryView from "./src/screens/HistoryView";
import { registerForPush } from "./src/notifications";

type Tab = "calendar" | "history";

export default function App() {
  const [tab, setTab] = useState<Tab>("calendar");

  useEffect(() => {
    // Fire and forget: request permission + register this device's FCM token.
    registerForPush();
  }, []);

  return (
    <SafeAreaView style={styles.safe}>
      <StatusBar barStyle="dark-content" />

      <View style={styles.header}>
        <Text style={styles.headerText}>💊 Pillbox</Text>
      </View>

      <View style={styles.body}>
        {tab === "calendar" ? <CalendarView /> : <HistoryView />}
      </View>

      <View style={styles.footer}>
        <FooterButton
          label="Calendar"
          active={tab === "calendar"}
          onPress={() => setTab("calendar")}
        />
        <FooterButton
          label="History"
          active={tab === "history"}
          onPress={() => setTab("history")}
        />
      </View>
    </SafeAreaView>
  );
}

function FooterButton({
  label,
  active,
  onPress,
}: {
  label: string;
  active: boolean;
  onPress: () => void;
}) {
  return (
    <TouchableOpacity
      style={[styles.footerButton, active && styles.footerButtonActive]}
      onPress={onPress}
    >
      <Text
        style={[
          styles.footerButtonText,
          active && styles.footerButtonTextActive,
        ]}
      >
        {label}
      </Text>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: "#fff" },
  header: {
    paddingVertical: 14,
    alignItems: "center",
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: "#e0e0e0",
  },
  headerText: { fontSize: 20, fontWeight: "700" },
  body: { flex: 1 },
  footer: {
    flexDirection: "row",
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: "#e0e0e0",
  },
  footerButton: { flex: 1, paddingVertical: 16, alignItems: "center" },
  footerButtonActive: { backgroundColor: "#e8f5e9" },
  footerButtonText: { fontSize: 16, color: "#666" },
  footerButtonTextActive: { color: "#2e7d32", fontWeight: "700" },
});
