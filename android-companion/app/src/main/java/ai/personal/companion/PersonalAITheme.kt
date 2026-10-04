package ai.personal.companion

/** Semantic companion tokens; dimensions are dp and text sizes are scaled sp. */
internal object PersonalAITheme {
    object ColorToken {
        val background = 0xFF03060D.toInt()
        val surface = 0xFF091118.toInt()
        val field = 0xFF070D12.toInt()
        val text = 0xFFEDF4F7.toInt()
        val secondaryText = 0xFF94A3B8.toInt()
        val accent = 0xFF61B3FB.toInt()
        val primaryAction = 0xFFD6EDF8.toInt()
        val border = 0xFF2A3E4A.toInt()
        val danger = 0xFFFFB2B2.toInt()
    }

    object Space {
        const val x1 = 4
        const val x2 = 8
        const val x3 = 12
        const val x4 = 16
        const val x5 = 20
        const val x6 = 24
        const val x8 = 32
        const val x10 = 40
    }

    object Type {
        const val display = 30f
        const val pageTitle = 22f
        const val sectionTitle = 18f
        const val body = 16f
        const val supporting = 14f
        const val control = 14f
        const val metadata = 12f
    }

    const val controlHeightDp = 48
    const val touchTargetDp = 48
    const val cornerRadiusDp = 14
}
