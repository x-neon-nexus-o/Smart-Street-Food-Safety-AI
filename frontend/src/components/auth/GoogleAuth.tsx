"use client";

import { GoogleOAuthProvider, GoogleLogin, CredentialResponse } from "@react-oauth/google";
import { useState } from "react";
import { api } from "@/lib/api";
import { setToken } from "@/lib/auth";

export default function GoogleAuth({
  onSuccess,
  onError,
}: {
  onSuccess: () => void;
  onError: (msg: string) => void;
}) {
  const [loading, setLoading] = useState(false);
  const clientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;

  if (!clientId) {
    return <p className="text-red-500 text-sm">Google Client ID is missing</p>;
  }

  const handleSuccess = async (credentialResponse: CredentialResponse) => {
    if (!credentialResponse.credential) {
      onError("Google login failed. No credential received.");
      return;
    }
    setLoading(true);
    try {
      const response = await api.loginWithGoogle(credentialResponse.credential);
      setToken(response.access_token);
      onSuccess();
    } catch (err: unknown) {
      onError(err instanceof Error ? err.message : String(err) || "Failed to authenticate with Google.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex justify-center w-full">
      {loading ? (
        <div className="h-10 w-full flex justify-center items-center rounded-full border border-gray-300">
           <span className="h-5 w-5 animate-spin rounded-full border-2 border-gray-300 border-t-gray-800"></span>
        </div>
      ) : (
        <GoogleOAuthProvider clientId={clientId}>
          <GoogleLogin
            onSuccess={handleSuccess}
            onError={() => onError("Google login failed")}
            useOneTap
            shape="pill"
            width="100%"
          />
        </GoogleOAuthProvider>
      )}
    </div>
  );
}
