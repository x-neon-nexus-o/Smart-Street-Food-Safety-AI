"use client";

import { MapContainer, TileLayer, Marker, Popup } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import L from "leaflet";
import Link from "next/link";
import { PublicStallLocation, ScoreBand } from "@/lib/types";

// Fix Leaflet's default icon issue in Next.js
delete (L.Icon.Default.prototype as unknown as Record<string, unknown>)._getIconUrl;

const createIcon = (color: string) => {
  return L.divIcon({
    className: "custom-leaflet-marker",
    html: `<div style="background-color: ${color}; width: 24px; height: 24px; border-radius: 50%; border: 3px solid white; box-shadow: 0 2px 5px rgba(0,0,0,0.3);"></div>`,
    iconSize: [24, 24],
    iconAnchor: [12, 12],
    popupAnchor: [0, -12],
  });
};

const ICONS = {
  good: createIcon("#22c55e"),
  fair: createIcon("#eab308"),
  poor: createIcon("#f97316"),
  bad: createIcon("#ef4444"),
  none: createIcon("#94a3b8"),
};

function getIconForBand(band: ScoreBand | null) {
  if (!band) return ICONS.none;
  return ICONS[band] || ICONS.none;
}

interface ReviewerMapProps {
  stalls: PublicStallLocation[];
}

export default function ReviewerMapComponent({ stalls }: ReviewerMapProps) {
  const defaultCenter = { lat: 20.5937, lng: 78.9629 };
  // Derive center from props without setState-in-effect
  const center =
    stalls.length > 0
      ? { lat: stalls[0].latitude, lng: stalls[0].longitude }
      : defaultCenter;

  return (
    <MapContainer
      center={[center.lat, center.lng]}
      zoom={stalls.length > 0 ? 14 : 5}
      scrollWheelZoom={true}
      style={{ height: "100%", width: "100%", zIndex: 0 }}
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      {stalls.map((stall) => (
        <Marker
          key={stall.code}
          position={[stall.latitude, stall.longitude]}
          icon={getIconForBand(stall.band)}
        >
          <Popup>
            <div className="p-1 min-w-[160px]">
              <h3 className="font-bold text-gray-900 mb-1">{stall.stall_name}</h3>
              {stall.score !== null ? (
                <div className="text-sm text-gray-700 mb-2">
                  Score: <span className="font-semibold">{Math.round(stall.score)}/100</span>
                  <div className="text-xs text-gray-500 capitalize">{stall.band} hygiene score</div>
                </div>
              ) : (
                <div className="text-sm text-gray-500 mb-2">Not assessed yet</div>
              )}
              <Link
                href={`/stall/${stall.code}`}
                className="block w-full text-center bg-blue-600 text-white rounded px-3 py-1.5 text-xs font-semibold hover:bg-blue-700"
              >
                View Stall
              </Link>
            </div>
          </Popup>
        </Marker>
      ))}
    </MapContainer>
  );
}
