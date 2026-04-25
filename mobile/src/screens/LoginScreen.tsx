/**
 * LoginScreen — Biometric authentication (camera/mic capture).
 *
 * Placeholder — full implementation in task 10.3.
 */

import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

const LoginScreen: React.FC = () => {
  return (
    <View style={styles.container}>
      <Text style={styles.title}>Memo Tracker</Text>
      <Text style={styles.subtitle}>Biometric Login</Text>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  title: { fontSize: 28, fontWeight: 'bold', marginBottom: 8 },
  subtitle: { fontSize: 16, color: '#666' },
});

export default LoginScreen;
