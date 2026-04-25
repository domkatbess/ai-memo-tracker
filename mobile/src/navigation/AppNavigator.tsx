import React from 'react';
import { createNativeStackNavigator } from '@react-navigation/native-stack';

import LoginScreen from '../screens/LoginScreen';
import DashboardScreen from '../screens/DashboardScreen';
import MemoFormScreen from '../screens/MemoFormScreen';
import VoiceMemoRegistrationScreen from '../screens/VoiceMemoRegistrationScreen';
import MemoDetailScreen from '../screens/MemoDetailScreen';
import SearchScreen from '../screens/SearchScreen';
import UserManagementScreen from '../screens/UserManagementScreen';
import UserRegistrationForm from '../screens/UserRegistrationForm';
import BiometricEnrollmentScreen from '../screens/BiometricEnrollmentScreen';

export type RootStackParamList = {
  Login: undefined;
  Dashboard: undefined;
  MemoForm: undefined;
  VoiceMemoRegistration: undefined;
  MemoDetail: { memoId: string };
  Search: undefined;
  UserManagement: undefined;
  UserRegistration: undefined;
  BiometricEnrollment: { userId: string };
};

const Stack = createNativeStackNavigator<RootStackParamList>();

const AppNavigator: React.FC = () => {
  return (
    <Stack.Navigator initialRouteName="Login">
      <Stack.Screen name="Login" component={LoginScreen} options={{ headerShown: false }} />
      <Stack.Screen name="Dashboard" component={DashboardScreen} options={{ title: 'Memo Tracker' }} />
      <Stack.Screen name="MemoForm" component={MemoFormScreen} options={{ title: 'Register Memo' }} />
      <Stack.Screen name="VoiceMemoRegistration" component={VoiceMemoRegistrationScreen} options={{ title: 'Voice Memo Registration' }} />
      <Stack.Screen name="MemoDetail" component={MemoDetailScreen} options={{ title: 'Memo Details' }} />
      <Stack.Screen name="Search" component={SearchScreen} options={{ title: 'Search Memos' }} />
      <Stack.Screen name="UserManagement" component={UserManagementScreen} options={{ title: 'User Management' }} />
      <Stack.Screen name="UserRegistration" component={UserRegistrationForm} options={{ title: 'Register User' }} />
      <Stack.Screen name="BiometricEnrollment" component={BiometricEnrollmentScreen} options={{ title: 'Biometric Enrollment' }} />
    </Stack.Navigator>
  );
};

export default AppNavigator;
