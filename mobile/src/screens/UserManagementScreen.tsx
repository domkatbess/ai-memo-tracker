/**
 * UserManagementScreen — Superuser: create/edit/deactivate users.
 *
 * Placeholder — full implementation in task 12.3.
 */

import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

const UserManagementScreen: React.FC = () => {
  return (
    <View style={styles.container}>
      <Text style={styles.title}>User Management</Text>
      <Text style={styles.subtitle}>User list and actions will appear here</Text>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  title: { fontSize: 24, fontWeight: 'bold', marginBottom: 8 },
  subtitle: { fontSize: 14, color: '#666' },
});

export default UserManagementScreen;
