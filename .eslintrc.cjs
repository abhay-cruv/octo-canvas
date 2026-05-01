/** @type {import('eslint').Linter.Config} */
module.exports = {
  root: true,
  parser: '@typescript-eslint/parser',
  parserOptions: {
    ecmaVersion: 2022,
    sourceType: 'module',
    ecmaFeatures: { jsx: true },
  },
  plugins: ['@typescript-eslint', 'react', 'react-hooks'],
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react/recommended',
    'plugin:react-hooks/recommended',
  ],
  settings: {
    react: { version: 'detect' },
  },
  rules: {
    '@typescript-eslint/no-explicit-any': 'warn',
    'prefer-const': 'error',
    'react/react-in-jsx-scope': 'off',
  },
  ignorePatterns: [
    'dist',
    'build',
    'node_modules',
    '.turbo',
    'coverage',
    'generated',
    '**/*.config.js',
    '**/*.config.cjs',
    '**/*.config.ts',
  ],
};
