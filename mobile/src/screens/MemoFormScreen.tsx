/**
 * MemoFormScreen — Form for registering incoming/outgoing memos.
 *
 * Placeholder — full implementation in task 11.3.
 */

import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

const MemoFormScreen: React.FC = () => {
  return (
    <View style={styles.container}>
      <Text style={styles.title}>Register Memo</Text>
      <Text style={styles.subtitle}>Memo form will appear here</Text>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  title: { fontSize: 24, fontWeight: 'bold', marginBottom: 8 },
  subtitle: { fontSize: 14, color: '#666' },
});

export default MemoFormScreen;
