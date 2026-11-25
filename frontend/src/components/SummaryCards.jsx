import { CalendarCheck2, Clock, Mic, Stethoscope } from "lucide-react";

export default function SummaryCards({
  doctorsCount,
  voiceReady,
  callStatus,
  appointments,
  lookupPhone,
}) {
  const bookedCount = appointments.filter((item) => item.status === "booked").length;

  const cards = [
    {
      label: "Available Doctors",
      value: doctorsCount !== null ? String(doctorsCount) : "—",
      detail: "Active clinic specialists",
      icon: Stethoscope,
      accent: "bg-sky-50 text-sky-700",
    },
    {
      label: "Voice Assistant",
      value:
        callStatus === "connected"
          ? "In Call"
          : voiceReady
            ? "Ready"
            : "Setup Needed",
      detail: voiceReady ? "SmallWebRTC + Gemini" : "Check backend .env keys",
      icon: Mic,
      accent: "bg-teal-50 text-teal-700",
    },
    {
      label: "Upcoming Bookings",
      value: lookupPhone ? String(bookedCount) : "—",
      detail: lookupPhone ? `For ${lookupPhone}` : "Enter phone in Appointments",
      icon: CalendarCheck2,
      accent: "bg-indigo-50 text-indigo-700",
    },
    {
      label: "Total Records Found",
      value: lookupPhone ? String(appointments.length) : "—",
      detail: lookupPhone ? "Includes cancelled history" : "Phone lookup required",
      icon: Clock,
      accent: "bg-slate-100 text-slate-700",
    },
  ];

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {cards.map((card) => {
        const Icon = card.icon;
        return (
          <div
            key={card.label}
            className="rounded-2xl border border-slate-200 bg-white p-5 shadow-xs"
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium uppercase tracking-wider text-slate-500">
                {card.label}
              </span>
              <div className={`flex h-9 w-9 items-center justify-center rounded-xl ${card.accent}`}>
                <Icon className="h-4 w-4" />
              </div>
            </div>
            <p className="mt-3 text-2xl font-semibold tracking-tight text-[#0F2942]">
              {card.value}
            </p>
            <p className="mt-1 text-xs text-slate-500">{card.detail}</p>
          </div>
        );
      })}
    </div>
  );
}
