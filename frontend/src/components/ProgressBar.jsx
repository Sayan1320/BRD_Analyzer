import { useState, useEffect } from "react";

const STEPS = [
  { label: "Extracting text with OCR...",           target: 33,  delay: 3000  },
  { label: "Analyzing requirements with Gemini...", target: 66,  delay: 12000 },
  { label: "Saving results to database...",         target: 90,  delay: 3000  },
  { label: "Complete!",                             target: 100, delay: 0     },
];

export function ProgressBar({ isLoading, isComplete, onReset }) {
  const [step, setStep] = useState(0);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    if (!isLoading) {
      setStep(0);
      setWidth(0);
      return;
    }

    const timeouts = [];

    const advance = (currentStep) => {
      if (currentStep >= STEPS.length - 1) return;
      const { target, delay } = STEPS[currentStep];
      setWidth(target);
      const t = setTimeout(() => {
        const nextStep = currentStep + 1;
        setStep(nextStep);
        advance(nextStep);
      }, delay);
      timeouts.push(t);
    };

    advance(0);

    return () => timeouts.forEach(clearTimeout);
  }, [isLoading]);

  useEffect(() => {
    if (isComplete) {
      setStep(STEPS.length - 1);
      setWidth(100);
    }
  }, [isComplete]);

  return (
    <div className="w-full">
      <div className="w-full bg-gray-200 rounded-full h-2">
        <div
          className="bg-blue-500 h-2 rounded-full transition-all duration-500"
          style={{ width: `${width}%` }}
        />
      </div>
      <p className="text-sm text-gray-600 mt-1">{STEPS[step]?.label}</p>
    </div>
  );
}
