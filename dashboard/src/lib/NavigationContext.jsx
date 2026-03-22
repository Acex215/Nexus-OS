import { createContext, useContext } from 'react';

export const NavigationContext = createContext(() => {});
export function useNavigation() { return useContext(NavigationContext); }
