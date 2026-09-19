"use client";

import { useState } from "react";

export default function DigilockerAuth({
  onError,
}: {
  onSuccess: () => void;
  onError: (msg: string) => void;
}) {
  const [loading, setLoading] = useState(false);

  const handleDigilockerLogin = async () => {
    setLoading(true);
    
    // Check if client ID is configured
    const clientId = process.env.NEXT_PUBLIC_DIGILOCKER_CLIENT_ID;
    const appUrl = process.env.NEXT_PUBLIC_APP_URL || "http://localhost:3000";
    
    if (!clientId) {
      onError("DigiLocker Client ID is not configured.");
      setLoading(false);
      return;
    }

    const redirectUri = encodeURIComponent(`${appUrl}/auth/digilocker/callback`);
    
    // Redirect to Digilocker Authorization URL
    window.location.href = `https://api.digitallocker.gov.in/public/oauth2/1/authorize?response_type=code&client_id=${clientId}&state=xyz&redirect_uri=${redirectUri}`;
  };

  return (
    <button
      type="button"
      onClick={handleDigilockerLogin}
      disabled={loading}
      className="w-full rounded-full border border-[#10220F] bg-[#FFFCEB] px-4 py-3 text-sm font-semibold text-[#10220F] flex justify-center items-center gap-2 hover:bg-[#F7F5C7] transition-colors shadow-[0_2px_8px_rgba(16,34,15,0.08)]"
    >
      {loading ? (
        <span className="h-5 w-5 animate-spin rounded-full border-2 border-[#10220F] border-t-transparent"></span>
      ) : (
        <>
          <span className="text-lg">🏛️</span> Continue with DigiLocker
        </>
      )}
    </button>
  );
}
