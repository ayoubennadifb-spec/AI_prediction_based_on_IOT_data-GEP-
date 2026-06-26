import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

const base = {
  width: 18,
  height: 18,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

export function ThermometerIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M14 14.76V5a2 2 0 1 0-4 0v9.76a4 4 0 1 0 4 0Z" />
    </svg>
  );
}

export function HumidityIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M12 2.69 6.34 8.35a8 8 0 1 0 11.32 0L12 2.69Z" />
    </svg>
  );
}

export function Co2Icon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M3 12a4 4 0 0 0 4 4h11a3 3 0 0 0 0-6 5 5 0 0 0-9.6-1.5A4 4 0 0 0 3 12Z" />
    </svg>
  );
}

export function ClockIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </svg>
  );
}

export function ForecastIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M3 17l5-5 4 3 6-7" />
      <path d="M16 8h3v3" />
    </svg>
  );
}
