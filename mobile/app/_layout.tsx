import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";

import { AuthProvider } from "@/src/auth/AuthContext";
import { SoftphoneProvider } from "@/src/softphone/SoftphoneContext";

export default function RootLayout() {
  return (
    <AuthProvider>
      <SoftphoneProvider>
        <StatusBar style="dark" />
        <Stack screenOptions={{ headerShown: false }} />
      </SoftphoneProvider>
    </AuthProvider>
  );
}
