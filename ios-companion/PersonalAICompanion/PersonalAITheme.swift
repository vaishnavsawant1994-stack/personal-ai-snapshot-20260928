import SwiftUI

/// Shared semantic values for the native companion. Font styles intentionally
/// use Dynamic Type roles so the system text size and accessibility settings win.
enum PersonalAITheme {
    enum ColorToken {
        static let background = Color(red: 0.02, green: 0.035, blue: 0.055)
        static let surface = Color(red: 0.05, green: 0.075, blue: 0.095)
        static let accent = Color(red: 0.38, green: 0.70, blue: 0.98)
        static let primaryText = Color.white
        static let secondaryText = Color.secondary
        static let border = Color(red: 0.14, green: 0.22, blue: 0.28)
        static let destructive = Color.red
    }

    enum Space {
        static let x1: CGFloat = 4
        static let x2: CGFloat = 8
        static let x3: CGFloat = 12
        static let x4: CGFloat = 16
        static let x5: CGFloat = 20
        static let x6: CGFloat = 24
        static let x8: CGFloat = 32
        static let x10: CGFloat = 40
    }

    enum Typography {
        static let display: Font = .largeTitle
        static let pageTitle: Font = .title3
        static let sectionTitle: Font = .headline
        static let body: Font = .body
        static let supporting: Font = .subheadline
        static let control: Font = .callout
        static let metadata: Font = .caption
    }

    static let touchTarget: CGFloat = 44
    static let controlCornerRadius: CGFloat = 13
}
