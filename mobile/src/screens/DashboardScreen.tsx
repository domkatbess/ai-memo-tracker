/**
 * DashboardScreen — Quick actions: register memo, search, voice input.
 *
 * Placeholder — full implementation in task 10.4.
 */

import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

const DashboardScreen: React.FC = () => {
  return (
    <View style={styles.container}>
      <Text style={styles.title}>Dashboard</Text>
      <Text style={styles.subtitle}>Quick actions will appear here</Text>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  title: { fontSize: 24, fontWeight: 'bold', marginBottom: 8 },
  subtitle: { fontSize: 14, color: '#666' },
});

export default DashboardScreen;
