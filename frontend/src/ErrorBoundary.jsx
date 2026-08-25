import { Component } from 'react'

class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, info) {
    console.error('ErrorBoundary caught:', error, info)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          padding: '40px', textAlign: 'center', color: '#d4d4d4',
          background: '#1e1e1e', height: '100vh', fontFamily: 'sans-serif'
        }}>
          <h2 style={{ color: '#e05555', marginBottom: '16px' }}>Something went wrong</h2>
          <p style={{ color: '#888', marginBottom: '24px' }}>
            {this.state.error?.message || 'An unexpected error occurred'}
          </p>
          <button
            onClick={() => { this.setState({ hasError: false }); window.location.reload() }}
            style={{
              padding: '10px 24px', background: '#0e639c', color: 'white',
              border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '14px'
            }}
          >
            Reload Page
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

export default ErrorBoundary
