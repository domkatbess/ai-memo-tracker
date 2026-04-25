/**
 * BiometricEnrollmentScreen — Capture face image and voice sample.
 *
 * Placeholder — full implementation in task 12.5.
 */

import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

const BiometricEnrollmentScreen: React.FC = () => {
  return (
    <View style={styles.container}>
      <Text style={styles.title}>Biometric Enrollment</Text>
      <Text style={styles.subtitle}>Face and voice capture will appear here</Text>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  title: { fontSize: 24, fontWeight: 'bold', marginBottom: 8 },
  subtitle: { fontSize: 14, color: '#666' },
});

export default BiometricEnrollmentScreen;
