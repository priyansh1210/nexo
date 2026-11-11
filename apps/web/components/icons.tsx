// Solar icons by 480 Design, CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/),
// copied from the @iconify-json/solar package. Only the icons the app uses are kept here.

const ICONS = {
  send: "<g fill=\"none\"><path stroke=\"currentColor\" stroke-width=\"1.5\" d=\"m18.636 15.67l1.716-5.15c1.5-4.498 2.25-6.747 1.062-7.934s-3.436-.438-7.935 1.062L8.33 5.364C4.7 6.574 2.885 7.18 2.37 8.067a2.72 2.72 0 0 0 0 2.73c.515.888 2.33 1.493 5.96 2.704c.584.194.875.291 1.119.454c.236.158.439.361.597.597c.163.244.26.535.454 1.118c1.21 3.63 1.816 5.446 2.703 5.962a2.72 2.72 0 0 0 2.731 0c.887-.516 1.492-2.331 2.703-5.962Z\"/><path fill=\"currentColor\" d=\"M16.212 8.848a.75.75 0 0 0-1.055-1.066zm-5.55 5.488l5.55-5.488l-1.055-1.066l-5.55 5.488z\"/></g>", // solar:plain-linear
  close: "<g fill=\"none\" stroke=\"currentColor\" stroke-linecap=\"round\" stroke-width=\"1.5\"><circle cx=\"12\" cy=\"12\" r=\"10\"/><path d=\"M14.5 9.50002L12 12M12 12L9.5 14.5M12 12L9.49998 9.5M12 12L14.5 14.5\"/></g>", // solar:close-circle-linear
  expand: "<path fill=\"none\" stroke=\"currentColor\" stroke-linecap=\"round\" stroke-linejoin=\"round\" stroke-width=\"1.5\" d=\"M19 9L12 15L5 9\"/>", // solar:alt-arrow-down-linear
  external: "<path fill=\"none\" stroke=\"currentColor\" stroke-linecap=\"round\" stroke-linejoin=\"round\" stroke-width=\"1.5\" d=\"M6 18L18 6M18 15V6H9\"/>", // solar:arrow-right-up-linear
  warning: "<g fill=\"none\" stroke=\"currentColor\" stroke-linecap=\"round\" stroke-width=\"1.5\"><path d=\"M11.6363 21H12.3637C17.7864 21 20.4978 21 21.5937 19.428C22.6897 17.856 21.4771 15.7061 19.0519 11.4063L18.6883 10.7615C15.7699 5.58716 14.3107 3 12 3C9.68925 3 8.23007 5.58716 5.31171 10.7615L4.94805 11.4063C2.52291 15.7061 1.31034 17.856 2.40626 19.428C3.50217 21 6.21356 21 11.6363 21Z\"/><path d=\"M12 8V13\"/><path stroke-linejoin=\"round\" d=\"M12 16H12.0001\"/></g>", // solar:danger-triangle-linear
  done: "<g fill=\"none\" stroke=\"currentColor\" stroke-linecap=\"round\" stroke-width=\"1.5\"><circle cx=\"12\" cy=\"12\" r=\"10\"/><path stroke-linejoin=\"round\" d=\"M8.5 12.5L10.5 14.5L15.5 9.5\"/></g>", // solar:check-circle-linear
} as const;

export type IconName = keyof typeof ICONS;

/** A decorative icon: its meaning must also be in the text or the control's label. */
export function Icon({ name, className = "size-4" }: { name: IconName; className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      aria-hidden="true"
      focusable="false"
      dangerouslySetInnerHTML={{ __html: ICONS[name] }}
    />
  );
}
